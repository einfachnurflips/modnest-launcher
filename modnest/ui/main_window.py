"""Hauptfenster: Seitenleiste (Home, Screenshots, Instanzen), Seiten in der Mitte, Spielen-Leiste unten."""
import os
import shutil
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QGraphicsDropShadowEffect, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QStackedWidget,
    QTabWidget, QVBoxLayout, QWidget,
)

from .. import accounts, backup, crash, game, installer, modpack, news
from ..config import APP_NAME, APP_VERSION, data_dir
from ..instances import KINDS, LOADERS, create_instance, delete_instance, duplicate_instance, list_instances
from ..sources import modrinth
from . import style
from .content_page import ContentPage
from .dialogs import DuplicateDialog, IconPickerDialog, NewInstanceDialog, SettingsDialog
from .extra_dialogs import CrashDialog, ExportDialog, PatchNotesDialog, WorldBackupsDialog
from .fmt import ago, duration
from .home_page import HomePage
from .icons import app_icon, instance_icon, logo_pixmap, reset_instance_icon, save_instance_icon
from .login_dialog import MicrosoftLoginDialog
from .screenshots_page import ScreenshotsPage
from .search_page import SearchPage
from .version_dialog import VersionDialog
from .workers import IconLoader, run_task
from ..i18n import tr

TAB_ICONS = {"mods": "🧩", "resourcepacks": "🎨", "shaderpacks": "✨"}
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.instances = []
        self.instance = None
        self.install_queue = []
        self.installing = False
        self.game_process = None
        self.game_instance = None
        self.game_started = 0.0
        self.icon_loader = IconLoader(self)
        self.accounts = accounts.AccountStore()
        if not self.accounts.accounts:
            # Erster Start: Offline-Konto aus dem bisherigen Spielernamen anlegen
            self.accounts.add(accounts.offline_account(settings.username or "Steve"))

        self.setWindowTitle(f"{APP_NAME} Launcher")
        self.setWindowIcon(app_icon())
        self.resize(1280, 820)
        self.setMinimumSize(1000, 660)
        self.setAcceptDrops(True)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        body.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.stack.setObjectName("pages")
        self.home = HomePage(settings, self.icon_loader)
        self.home.playRequested.connect(lambda inst: self.play(inst))
        self.home.openInstance.connect(self.open_instance)
        self.home.joinWorld.connect(lambda inst, folder: self.play(inst, ("world", folder)))
        self.home.joinServer.connect(lambda inst, addr: self.play(inst, ("server", addr)))
        self.home.updateRequested.connect(self.apply_updates)
        self.home.patchNotesRequested.connect(self.show_patch_notes)
        self.home.newInstanceRequested.connect(self.new_instance)
        self.home.importRequested.connect(self.import_modpack)
        self.screens = ScreenshotsPage(settings)
        self.screens.message.connect(self.status)
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.screens)
        self.stack.addWidget(self._build_instance_page())
        body.addWidget(self.stack, 1)

        outer.addWidget(self._build_playbar())

        self.game_timer = QTimer(self)
        self.game_timer.timeout.connect(self._check_game)
        self._update_account()
        self.reload_instances(select=settings.last_instance, show_home=True)
        run_task(news.launcher_update, self.home.show_launcher_update)

    # --- Aufbau ------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(268)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 18, 16, 16)
        sl.setSpacing(6)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(36))
        brand.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel(APP_NAME)
        name.setObjectName("brand")
        ver = QLabel(f"Launcher v{APP_VERSION}")
        ver.setObjectName("brandsub")
        brand_text.addWidget(name)
        brand_text.addWidget(ver)
        brand.addLayout(brand_text, 1)
        sl.addLayout(brand)
        sl.addSpacing(14)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(False)
        self.nav_buttons = {}
        for key, text in (("home", tr("🏠   Home")), ("screens", tr("🖼   Screenshots"))):
            btn = QPushButton(text)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_buttons[key] = btn
            sl.addWidget(btn)
        sl.addSpacing(12)

        section = QHBoxLayout()
        lbl = QLabel(tr("INSTANZEN"))
        lbl.setObjectName("section")
        section.addWidget(lbl, 1)
        for text, tip, slot in (("📦", tr("Modpack importieren (.mrpack / CurseForge-ZIP)"), self.import_modpack),
                                ("＋", tr("Neue Instanz"), self.new_instance)):
            b = QPushButton(text)
            b.setObjectName("iconbtn")
            b.setToolTip(tip)
            b.clicked.connect(slot)
            section.addWidget(b)
        sl.addLayout(section)

        self.instance_list = QListWidget()
        self.instance_list.setObjectName("instances")
        self.instance_list.setIconSize(QSize(38, 38))
        self.instance_list.itemClicked.connect(lambda item: self.open_instance(self.instances[self.instance_list.row(item)]))
        self.instance_list.currentRowChanged.connect(self._row_changed)
        self.instance_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.instance_list.customContextMenuRequested.connect(self._instance_menu_at)
        sl.addWidget(self.instance_list, 1)

        settings_btn = QPushButton(tr("⚙   Einstellungen"))
        settings_btn.setObjectName("nav")
        settings_btn.clicked.connect(self.open_settings)
        sl.addWidget(settings_btn)
        return side

    def _build_instance_page(self) -> QWidget:
        page = QWidget()
        cl = QVBoxLayout(page)
        cl.setContentsMargins(28, 22, 28, 14)
        cl.setSpacing(4)

        header = QHBoxLayout()
        self.avatar_btn = QPushButton()
        self.avatar_btn.setObjectName("avatar")
        self.avatar_btn.setIconSize(QSize(60, 60))
        self.avatar_btn.setFixedSize(64, 64)
        self.avatar_btn.setToolTip(tr("Icon ändern"))
        self.avatar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.avatar_btn.clicked.connect(lambda: self._icon_menu().exec(self.avatar_btn.mapToGlobal(
            self.avatar_btn.rect().bottomLeft())))
        header.addWidget(self.avatar_btn)
        header.addSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(6)
        self.title = QLabel()
        self.title.setObjectName("title")
        titles.addWidget(self.title)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        titles.addLayout(self.chips)
        header.addLayout(titles, 1)
        share = QPushButton(tr("📤  Teilen"))
        share.setToolTip(tr("Als Modpack exportieren (.mrpack / CurseForge)"))
        share.clicked.connect(self.export_modpack)
        header.addWidget(share)
        folder = QPushButton("📁")
        folder.setObjectName("iconbtn")
        folder.setToolTip(tr("Instanz-Ordner öffnen"))
        folder.clicked.connect(self.open_instance_folder)
        header.addWidget(folder)
        more = QPushButton("⋯")
        more.setObjectName("iconbtn")
        more.setToolTip(tr("Weitere Aktionen"))
        more.clicked.connect(lambda: self._instance_menu().exec(more.mapToGlobal(more.rect().bottomLeft())))
        header.addWidget(more)
        cl.addLayout(header)
        cl.addSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.pages: dict[str, ContentPage] = {}
        for kind in KINDS:
            cp = ContentPage(kind, self.icon_loader)
            cp.message.connect(self.status)
            cp.versionRequested.connect(self.change_version)
            cp.irisRequested.connect(self.install_iris)
            self.pages[kind] = cp
            self.tabs.addTab(cp, f"{TAB_ICONS[kind]}  {tr(KINDS[kind]['label'])}")
        self.search_page = SearchPage(self.settings, self.icon_loader)
        self.search_page.message.connect(self.status)
        self.search_page.installRequested.connect(self.queue_install)
        self.search_page.versionPickRequested.connect(self.pick_version_for_install)
        self.tabs.addTab(self.search_page, tr("🔍  Entdecken"))
        self.tabs.currentChanged.connect(self._tab_changed)
        cl.addWidget(self.tabs, 1)
        return page

    def _build_playbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("playbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(24, 14, 24, 14)
        bl.setSpacing(14)
        status_col = QVBoxLayout()
        status_col.setSpacing(6)
        self.status_label = QLabel(tr("Bereit."))
        self.status_label.setObjectName("statustext")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        status_col.addWidget(self.status_label)
        status_col.addWidget(self.progress)
        bl.addLayout(status_col, 1)
        self.account_btn = QPushButton()
        self.account_btn.setObjectName("account")
        self.account_menu = QMenu(self)
        self.account_menu.aboutToShow.connect(self._fill_account_menu)
        self.account_btn.setMenu(self.account_menu)
        bl.addWidget(self.account_btn)
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("play")
        glow = QGraphicsDropShadowEffect(self.play_btn)
        glow.setBlurRadius(28)
        glow.setOffset(0, 4)
        glow.setColor(QColor(16, 185, 129, 110))
        self.play_btn.setGraphicsEffect(glow)
        self.play_btn.clicked.connect(lambda: self.play())
        bl.addWidget(self.play_btn)
        self._reset_play()
        return bar

    # --- Navigation --------------------------------------------------------
    def show_page(self, key: str) -> None:
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)
        if key == "home":
            self.instance_list.clearSelection()
            self.home.refresh(self.instances, None)
            self.stack.setCurrentWidget(self.home)
        elif key == "screens":
            self.instance_list.clearSelection()
            self.screens.set_instances(self.instances)
            self.screens.reload()
            self.stack.setCurrentWidget(self.screens)
        self._update_play_label()

    def open_instance(self, inst) -> None:
        if inst not in self.instances:
            return
        for btn in self.nav_buttons.values():
            btn.setChecked(False)
        row = self.instances.index(inst)
        if self.instance_list.currentRow() != row:
            self.instance_list.setCurrentRow(row)
        else:
            self._select_instance(inst)
        self.instance_list.item(row).setSelected(True)
        self.stack.setCurrentIndex(2)
        self._update_play_label()

    def _row_changed(self, row: int) -> None:
        if 0 <= row < len(self.instances):
            self._select_instance(self.instances[row])
            for btn in self.nav_buttons.values():
                btn.setChecked(False)
            self.stack.setCurrentIndex(2)
            self._update_play_label()

    # --- Instanzen ---------------------------------------------------------
    def reload_instances(self, select: str = "", show_home: bool = False) -> None:
        self.instances = list_instances()
        self.instance_list.blockSignals(True)
        self.instance_list.clear()
        for inst in self.instances:
            sub = f"{LOADERS.get(inst.loader, inst.loader)} · {inst.mc_version}"
            item = QListWidgetItem(instance_icon(inst, 38), f"{inst.name}\n{sub}")
            item.setSizeHint(QSize(0, 58))
            item.setToolTip(tr("Zuletzt gespielt: {t}").format(t=ago(inst.last_played)))
            self.instance_list.addItem(item)
        self.instance_list.blockSignals(False)
        match = next((i for i in self.instances if str(i.path) == select), None)
        if match is None and self.instances:
            match = self.instances[0]
        self.instance = None
        if match is not None:
            self._select_instance(match)
        else:
            for p in self.pages.values():
                p.set_instance(None)
            self.search_page.set_instance(None)
        self.screens.set_instances(self.instances)
        if show_home or match is None:
            self.show_page("home")
        else:
            self.open_instance(match)

    def _select_instance(self, inst) -> None:
        if inst is self.instance:
            return
        self.instance = inst
        self.settings.last_instance = str(inst.path)
        self.settings.save()
        for page in self.pages.values():
            page.set_instance(inst)
        self.search_page.set_instance(inst)
        self._update_header()

    def _update_header(self) -> None:
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        inst = self.instance
        if not inst:
            return
        self.title.setText(inst.name)
        self.avatar_btn.setIcon(instance_icon(inst, 60))
        chips = [(f"Minecraft {inst.mc_version}", "chip"), (LOADERS.get(inst.loader, inst.loader), "chipaccent")]
        for kind, info in KINDS.items():
            count = len(inst.content[kind].items)
            if count:
                chips.append((f"{count} {tr(info['singular'] if count == 1 else info['label'])}", "chip"))
        if inst.playtime:
            chips.append(("⏱ " + tr("{t} gespielt").format(t=duration(inst.playtime)), "chip"))
        for text, name in chips:
            chip = QLabel(text)
            chip.setObjectName(name)
            self.chips.addWidget(chip)
        self.chips.addStretch(1)
        for i, (kind, info) in enumerate(KINDS.items()):
            count = len(inst.content[kind].items)
            self.tabs.setTabText(i, f"{TAB_ICONS[kind]}  {tr(info['label'])}" + (f"  {count}" if count else ""))
        row = self.instances.index(inst) if inst in self.instances else -1
        if row >= 0:
            item = self.instance_list.item(row)
            item.setIcon(instance_icon(inst, 38))
            item.setText(f"{inst.name}\n{LOADERS.get(inst.loader, inst.loader)} · {inst.mc_version}")

    def _tab_changed(self, index: int) -> None:
        page = self.tabs.widget(index)
        if isinstance(page, ContentPage):
            page.refresh()
            self.search_page.set_kind(page.kind)
        else:
            self.search_page.refresh_categories()
        self._update_header()

    def _instance_menu_at(self, pos) -> None:
        item = self.instance_list.itemAt(pos)
        if item is None:
            return
        self.open_instance(self.instances[self.instance_list.row(item)])
        self._instance_menu().exec(self.instance_list.viewport().mapToGlobal(pos))

    def _instance_menu(self) -> QMenu:
        menu = QMenu(self)
        if not self.instance:
            return menu
        menu.addAction(tr("▶  Spielen"), lambda: self.play(self.instance))
        menu.addSeparator()
        menu.addMenu(self._icon_menu())
        menu.addAction(tr("✏  Umbenennen …"), self.rename_instance)
        menu.addAction(tr("⧉  Kopieren …"), self.duplicate_instance)
        menu.addAction(tr("📤  Als Modpack teilen …"), self.export_modpack)
        menu.addAction(tr("💾  Welt-Backups …"), lambda: WorldBackupsDialog(self.instance, self.settings, self).exec())
        menu.addAction(tr("📁  Ordner öffnen"), self.open_instance_folder)
        menu.addSeparator()
        menu.addAction(tr("🗑  Löschen …"), self.delete_instance)
        return menu

    def _icon_menu(self) -> QMenu:
        menu = QMenu(tr("🖼  Icon ändern"), self)
        menu.addAction(tr("Bild auswählen …"), self.icon_from_file)
        menu.addAction(tr("Icon eines Mods/Packs verwenden …"), self.icon_from_content)
        reset = menu.addAction(tr("Standard-Icon"), self.icon_reset)
        reset.setEnabled(bool(self.instance and self.instance.icon_path))
        return menu

    def icon_from_file(self, path: str | None = None) -> None:
        if not self.instance:
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Icon auswählen"), str(Path.home() / "Pictures"),
                                                  tr("Bilder (*.png *.jpg *.jpeg *.webp *.gif *.bmp)"))
        if path:
            if save_instance_icon(self.instance, QImage(path)):
                self._update_header()
                self.status(tr("✔ Icon geändert."))
            else:
                QMessageBox.warning(self, tr("Icon"), tr("Das Bild konnte nicht geladen werden."))

    def icon_from_content(self) -> None:
        dlg = IconPickerDialog(self.instance, self.icon_loader, self)
        if dlg.exec() and dlg.pixmap is not None:
            save_instance_icon(self.instance, dlg.pixmap)
            self._update_header()

    def icon_reset(self) -> None:
        reset_instance_icon(self.instance)
        self._update_header()

    def new_instance(self) -> None:
        dlg = NewInstanceDialog(self)
        if dlg.exec():
            name, version, loader = dlg.values()
            if not name or not version or " " in version:
                QMessageBox.warning(self, tr("Neue Instanz"), tr("Bitte Name und eine gültige Minecraft-Version angeben."))
                return
            inst = create_instance(name, version, loader)
            self.reload_instances(select=str(inst.path))

    def rename_instance(self) -> None:
        name, ok = QInputDialog.getText(self, tr("Instanz umbenennen"), tr("Neuer Name:"), text=self.instance.name)
        if ok and name.strip():
            self.instance.name = name.strip()
            self.instance.save()
            self._update_header()

    def duplicate_instance(self) -> None:
        dlg = DuplicateDialog(self.instance, self)
        if not dlg.exec() or not dlg.name.text().strip():
            return
        src, name = self.instance, dlg.name.text().strip()
        worlds, screens = dlg.worlds.isChecked(), dlg.screens.isChecked()
        self.on_progress(tr("Kopiere „{name}“ …").format(name=src.name), 0, 0)
        run_task(lambda: duplicate_instance(src, name, worlds, screens),
                 lambda inst: (self._done(tr("✔ Kopie „{name}“ erstellt.").format(name=inst.name)),
                               self.reload_instances(select=str(inst.path))),
                 lambda err: (self._done(tr("⚠ Kopieren fehlgeschlagen.")),
                              QMessageBox.warning(self, tr("Kopieren"), err)))

    def open_instance_folder(self) -> None:
        if self.instance:
            os.startfile(self.instance.path)  # noqa: S606

    def delete_instance(self) -> None:
        if not self.instance:
            return
        if QMessageBox.question(self, tr("Instanz löschen"),
                                tr("„{name}“ inklusive aller Mods und Welten löschen?\n\n"
                                   "Tipp: Welt-Backups im Backup-Ordner bleiben erhalten.").format(name=self.instance.name)) \
                == QMessageBox.StandardButton.Yes:
            delete_instance(self.instance)
            self.instance = None
            self.reload_instances(show_home=True)

    # --- Modpacks teilen ---------------------------------------------------
    def export_modpack(self) -> None:
        if not self.instance:
            return
        dlg = ExportDialog(self.instance, self.settings, self)
        if not dlg.exec() or dlg.target is None:
            return
        inst, target, fmt, version = self.instance, dlg.target, dlg.fmt, dlg.version.text().strip() or "1.0.0"
        author = self.accounts.active.name if self.accounts.active else ""

        def work(progress):
            if fmt == "mrpack":
                return modpack.export_mrpack(inst, target, version, progress=progress)
            return modpack.export_curseforge(inst, target, self.settings, version, author, progress=progress)

        def done(stats):
            self._done(tr("✔ Modpack gespeichert: {path}").format(path=target))
            QMessageBox.information(self, tr("Modpack geteilt"), tr(
                tr("Gespeichert unter:\n{path}\n\n{linked} Datei(en) als Download-Link, {embedded} direkt eingepackt.\n"
                "Die Datei kann in ModNest, Prism, Modrinth App, CurseForge App u.a. importiert werden.")).format(
                path=target, **stats))
            os.startfile(target.parent)  # noqa: S606

        run_task(work, done, lambda err: (self._done(tr("⚠ Export fehlgeschlagen.")),
                                          QMessageBox.warning(self, tr("Export"), err)), self.on_progress)

    def import_modpack(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Modpack importieren"), str(Path.home() / "Downloads"),
                                                  tr("Modpacks (*.mrpack *.zip)"))
        if not path:
            return
        p = Path(path)
        if modpack.detect_pack(p) is None:
            QMessageBox.warning(self, tr("Import"), tr("Diese Datei ist kein Modpack (.mrpack oder CurseForge-ZIP)."))
            return

        def done(inst):
            manual = getattr(inst, "import_manual", [])
            self._done(tr("✔ Modpack „{name}“ importiert.").format(name=inst.name))
            self.reload_instances(select=str(inst.path))
            if manual:
                QMessageBox.information(self, tr("Fast fertig"), tr(
                    tr("Diese Mods erlauben keinen automatischen Download und müssen manuell von CurseForge "
                    "geladen werden:\n\n{mods}")).format(mods="\n".join("• " + m for m in manual)))

        run_task(lambda progress: modpack.import_pack(p, self.settings, progress), done,
                 lambda err: (self._done(tr("⚠ Import fehlgeschlagen.")), QMessageBox.warning(self, tr("Import"), err)),
                 self.on_progress)

    # --- Drag & Drop -------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        files = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        added = {k: 0 for k in KINDS}
        for f in files:
            suffix = f.suffix.lower()
            if suffix == ".mrpack" or (suffix == ".zip" and modpack.detect_pack(f)):
                self.import_modpack(str(f))
                continue
            if suffix in IMAGE_EXTS and self.instance:
                if QMessageBox.question(self, tr("Icon"), tr("„{file}“ als Icon für „{name}“ verwenden?").format(
                        file=f.name, name=self.instance.name)) == QMessageBox.StandardButton.Yes:
                    self.icon_from_file(str(f))
                continue
            if not self.instance:
                continue
            kind = self._classify(f)
            if kind:
                shutil.copy2(f, self.instance.content[kind].folder / f.name)
                added[kind] += 1
        if any(added.values()):
            for page in self.pages.values():
                page.refresh()
            self._update_header()
            parts = [f"{n} {tr(KINDS[k]['label'])}" for k, n in added.items() if n]
            self.status(tr("✔ Hinzugefügt: {what} (unter „Unkategorisiert“)").format(what=", ".join(parts)))
        event.acceptProposedAction()

    @staticmethod
    def _classify(path: Path) -> str | None:
        suffix = path.suffix.lower()
        if suffix == ".jar":
            return "mods"
        if suffix != ".zip":
            return None
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
        except (OSError, zipfile.BadZipFile):
            return None
        if any(n == "shaders/" or n.startswith("shaders/") for n in names):
            return "shaderpacks"
        if "pack.mcmeta" in names:
            return "resourcepacks"
        return None

    # --- Einstellungen & Konten --------------------------------------------
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            QApplication.instance().setStyleSheet(style.build_style(data_dir(), self.settings.theme))
            for page in self.pages.values():
                page.refresh()
            self._update_header()
            if self.stack.currentWidget() is self.home:
                self.home.refresh(self.instances, None)
            self._update_account()
            self.status(tr("Einstellungen gespeichert."))
            if getattr(dlg, "language_changed", False):
                QMessageBox.information(self, "ModNest", tr("Starte den Launcher neu, um die Sprache zu wechseln.\n"
                                                            "Restart the launcher to change the language."))

    def _update_account(self) -> None:
        acc = self.accounts.active
        icon = "🟢" if acc and acc.kind == "microsoft" else "👤"
        label = (f"{acc.name} (Microsoft)" if acc.kind == "microsoft" else f"{acc.name} (Offline)") if acc else tr("Kein Konto")
        self.account_btn.setText(f"{icon}  {label}   ")
        self.home.set_display_name(acc.name if acc else "")

    def _fill_account_menu(self) -> None:
        menu = self.account_menu
        menu.clear()
        active = self.accounts.active
        for acc in self.accounts.accounts:
            action = menu.addAction(acc.label, lambda a=acc: self._switch_account(a))
            action.setCheckable(True)
            action.setChecked(active is not None and acc.id == active.id)
        menu.addSeparator()
        menu.addAction(tr("➕ Microsoft-Konto hinzufügen …"), self.add_microsoft_account)
        menu.addAction(tr("➕ Offline-Konto hinzufügen …"), self.add_offline_account)
        if active:
            menu.addSeparator()
            menu.addAction(tr("Abmelden: {name}").format(name=active.name), lambda: self._remove_account(active))

    def _switch_account(self, acc) -> None:
        self.accounts.set_active(acc)
        self._update_account()

    def add_microsoft_account(self) -> None:
        if not self.settings.ms_client_id.strip():
            QMessageBox.information(
                self, tr("Microsoft-Login"),
                tr("Für den Microsoft-Login wird eine Azure Client-ID benötigt.\n\n"
                   "Trag sie unter ⚙ Einstellungen ein. Wie du sie bekommst, steht in der README."))
            self.open_settings()
            if not self.settings.ms_client_id.strip():
                return
        dlg = MicrosoftLoginDialog(self.settings, self)
        if dlg.exec() and dlg.account:
            self.accounts.add(dlg.account)
            self._update_account()
            self.status(tr("✔ Angemeldet als {name}.").format(name=dlg.account.name))

    def add_offline_account(self) -> None:
        name, ok = QInputDialog.getText(self, tr("Offline-Konto"), tr("Spielername (3–16 Zeichen, A–Z, 0–9, _):"))
        name = name.strip()
        if not ok or not name:
            return
        if not (3 <= len(name) <= 16) or not all(c.isascii() and (c.isalnum() or c == "_") for c in name):
            QMessageBox.warning(self, tr("Offline-Konto"), tr("Ungültiger Name. Erlaubt sind 3–16 Zeichen: A–Z, 0–9 und _."))
            return
        self.accounts.add(accounts.offline_account(name))
        self._update_account()

    def _remove_account(self, acc) -> None:
        if QMessageBox.question(self, tr("Abmelden"), tr("Konto „{label}“ aus dem Launcher entfernen?").format(
                label=acc.label)) == QMessageBox.StandardButton.Yes:
            self.accounts.remove(acc)
            self._update_account()

    # --- Status ------------------------------------------------------------
    def status(self, text: str) -> None:
        self.status_label.setText(text)

    def on_progress(self, text, value: int, maximum: int) -> None:
        if text:
            self.status_label.setText(text)
        self.progress.show()
        if maximum > 0:
            self.progress.setRange(0, maximum)
            self.progress.setValue(min(value, maximum))
        elif text:
            self.progress.setRange(0, 0)   # unbestimmt

    def _done(self, text: str) -> None:
        self.progress.hide()
        self.status(text)

    # --- Installieren, Versionen & Updates ---------------------------------
    def queue_install(self, project, category, release=None, instance=None, pin=None) -> None:
        inst = instance or self.instance
        if not inst:
            return
        self.install_queue.append((inst, project, category, release, pin))
        self._next_install()

    def pick_version_for_install(self, project, category) -> None:
        installed = self.instance.content[project.kind].find_project(project.source, project.project_id)
        dlg = VersionDialog(self.settings, self.instance, project, installed.version_id if installed else "",
                            self.icon_loader, self)
        if dlg.exec() and dlg.selected:
            self.queue_install(project, category, dlg.selected)

    def change_version(self, kind: str, item) -> None:
        project = installer.project_from_item(item, kind)
        dlg = VersionDialog(self.settings, self.instance, project, item.version_id, self.icon_loader, self)
        if dlg.exec() and dlg.selected:
            self.queue_install(project, item.category, dlg.selected)

    def apply_updates(self, inst, ups: list) -> None:
        for upd in ups:
            self.queue_install(installer.project_from_item(upd.item, upd.kind), upd.item.category, upd.release,
                               instance=inst, pin=False)

    def install_iris(self) -> None:
        self.status(tr("Suche Iris auf Modrinth …"))
        run_task(lambda: modrinth.get_project("iris", "mods"),
                 lambda proj: self.queue_install(proj, None, None),
                 lambda err: self._done(tr("⚠ Iris konnte nicht gefunden werden: {e}").format(e=err)))

    def _next_install(self) -> None:
        if self.installing or not self.install_queue:
            return
        self.installing = True
        inst, project, category, release, pin = self.install_queue.pop(0)

        def work(progress):
            return installer.install_project(inst, project, self.settings, category, progress, release, pin)

        def done(names):
            self.installing = False
            extra = tr(" (+ {n} Abhängigkeit(en))").format(n=len(names) - 1) if len(names) > 1 else ""
            version = tr(" in Version {v}").format(v=release.version_name) if release else ""
            self._done(tr("✔ {title}{version} installiert{extra}.").format(title=project.title, version=version,
                                                                         extra=extra))
            self._after_install(inst)

        def fail(err):
            self.installing = False
            self._done(tr("⚠ {title}: Installation fehlgeschlagen.").format(title=project.title))
            QMessageBox.warning(self, tr("Installation fehlgeschlagen"), f"{project.title}:\n\n{err}")
            self._after_install(inst)

        run_task(work, done, fail, self.on_progress)

    def _after_install(self, inst) -> None:
        if inst is self.instance:
            for page in self.pages.values():
                page.refresh()
            self.search_page.mark_installed()
            self._update_header()
        self._next_install()

    def show_patch_notes(self, item) -> None:
        self.status(tr("Lade Patch-Notes …"))
        run_task(lambda: news.patch_notes_html(item.content_path),
                 lambda html: (self._done(tr("Bereit.")), PatchNotesDialog(item.title, html, self).exec()),
                 lambda err: self._done(tr("⚠ Patch-Notes konnten nicht geladen werden.")))

    # --- Spielen -----------------------------------------------------------
    def _update_play_label(self) -> None:
        if self.game_process is None:
            self._reset_play()

    def _play_target(self):
        if self.stack.currentWidget() is self.home:
            return self.home.focus
        return self.instance

    def play(self, inst=None, quick_play=None) -> None:
        inst = inst or self._play_target()
        if not inst or self.game_process is not None:
            if self.game_process is not None:
                self.status(tr("Minecraft läuft bereits."))
            return
        if self.installing:
            QMessageBox.information(self, tr("Bitte warten"), tr("Es werden gerade noch Inhalte installiert."))
            return
        account = self.accounts.active
        if account is None:
            QMessageBox.information(self, tr("Kein Konto"), tr("Bitte zuerst über den Konto-Button ein Konto hinzufügen."))
            return
        if quick_play and quick_play[0] == "world" and not game.supports_quick_play(inst.mc_version):
            QMessageBox.information(self, tr("Direkt beitreten"), tr(
                tr("Direkt in eine Welt springen geht erst ab Minecraft 1.20. Das Spiel startet normal.")))
            quick_play = None
        store = self.accounts
        client_id = self.settings.ms_client_id.strip()
        self.play_btn.setEnabled(False)
        self.play_btn.setText(tr("Startet …"))

        def work(progress):
            if account.kind == "microsoft":
                progress(tr("Melde {name} bei Microsoft an …").format(name=account.name), 0, 0)
                accounts.refresh(account, client_id)
            inst.write_resourcepack_order()
            return game.launch(inst, self.settings, account, progress, quick_play)

        def done(proc):
            store.save()          # ggf. neuer Refresh-Token
            self._update_account()
            self.game_process = proc
            self.game_instance = inst
            self.game_started = time.time()
            inst.last_played = self.game_started
            inst.save()
            self.play_btn.setText(tr("●   LÄUFT"))
            where = ""
            if quick_play:
                where = tr(" → {target}").format(target=quick_play[1])
            self._done(tr("Minecraft läuft ({name}){where}.").format(name=inst.name, where=where))
            self.game_timer.start(2000)

        def fail(err):
            self._reset_play()
            self._done(tr("⚠ Start fehlgeschlagen."))
            QMessageBox.critical(self, tr("Start fehlgeschlagen"), err)

        run_task(work, done, fail, self.on_progress)

    def _check_game(self) -> None:
        if not self.game_process or self.game_process.poll() is None:
            return
        code = self.game_process.returncode
        inst, started = self.game_instance, self.game_started
        self.game_process = None
        self.game_timer.stop()
        self._reset_play()
        inst.playtime += int(time.time() - started)
        inst.save()
        if inst is self.instance:
            self._update_header()
        self.status(tr("Minecraft wurde beendet – {t} gespielt.").format(t=duration(int(time.time() - started))))
        self._after_game_backups(inst, started)
        if code not in (0, None) and time.time() - started > 3:
            info = crash.analyze(inst.path, started)
            CrashDialog(info, inst, self, disable_callback=self._disable_mod).exec()
        if self.stack.currentWidget() is self.home:
            self.home.refresh(self.instances, None)

    def _disable_mod(self, mod) -> None:
        if self.game_instance is not None:
            self.game_instance.content["mods"].set_enabled(mod.file, False)
            self.game_instance.save()
            if self.game_instance is self.instance:
                self.pages["mods"].refresh()

    def _after_game_backups(self, inst, started: float) -> None:
        settings = self.settings

        def work():
            worlds, screens = [], 0
            if settings.backup_worlds:
                worlds = backup.backup_changed_worlds(inst, settings, started)
            if settings.backup_screenshots:
                screens = backup.backup_screenshots(inst, settings)
            return worlds, screens

        def done(result):
            worlds, screens = result
            parts = []
            if worlds:
                parts.append(tr("{n} Welt(en)").format(n=len(worlds)))
            if screens:
                parts.append(tr("{n} Screenshot(s)").format(n=screens))
            if parts:
                self.status(self.status_label.text() + "  " + tr("💾 Gesichert: {what}").format(what=", ".join(parts)))

        if settings.backup_worlds or settings.backup_screenshots:
            run_task(work, done, lambda err: self.status(tr("⚠ Backup fehlgeschlagen: {e}").format(e=err)))

    def _reset_play(self) -> None:
        self.play_btn.setText(tr("▶   SPIELEN"))
        self.play_btn.setEnabled(bool(self.instances))

    def closeEvent(self, event) -> None:
        for page in self.pages.values():
            if page.instance:
                page.save_layout()
        super().closeEvent(event)
