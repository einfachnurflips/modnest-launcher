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
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QStackedWidget,
    QTabWidget, QVBoxLayout, QWidget,
)

from .. import accounts, backup, compat, crash, discord_rpc, game, importers, installer, modpack, news, packs, shortcuts, updater
from ..keys import DEFAULT_KEYS
from ..config import APP_NAME, APP_VERSION, data_dir
from ..instances import (
    KINDS, LOADERS, create_instance, delete_instance, duplicate_instance, list_instances, save_defaults,
)
from ..sources import SourceError, modrinth
from . import style
from .content_page import ContentPage
from .comfort_dialogs import ImportLaunchersDialog, LogWindow, SkinDialog
from .instance_list import InstanceList
from .packs_page import ManualDownloadDialog, PackVersionDialog, PacksPage
from .tools_dialogs import ChangelogDialog, PerfDialog
from .dialogs import DuplicateDialog, IconPickerDialog, InstanceSettingsDialog, NewInstanceDialog, SettingsDialog
from .extra_dialogs import CrashDialog, ExportDialog, PatchNotesDialog, WorldBackupsDialog
from .fmt import duration
from .home_page import HomePage
from .icons import app_icon, instance_icon, logo_pixmap, reset_instance_icon, save_ico, save_instance_icon
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
        self.pack_busy = False
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
        self.home.packUpdateRequested.connect(self.update_pack)
        self.home.changelogRequested.connect(self.show_changelog)
        self.home.launcherUpdateRequested.connect(self.update_launcher)
        self.packs_page = PacksPage(settings, self.icon_loader)
        self.packs_page.installRequested.connect(self.install_pack)
        self.screens = ScreenshotsPage(settings)
        self.screens.message.connect(self.status)
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.screens)
        self.stack.addWidget(self._build_instance_page())
        self.stack.addWidget(self.packs_page)
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
        for key, text in (("home", tr("🏠   Home")), ("packs", tr("📦   Modpacks")),
                          ("screens", tr("🖼   Screenshots"))):
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
        imp = QPushButton("📥")
        imp.setObjectName("iconbtn")
        imp.setToolTip(tr("Importieren: Modpack-Datei oder Instanzen aus anderen Launchern"))
        imp_menu = QMenu(self)
        imp_menu.addAction(tr("📦  Modpack-Datei importieren (.mrpack / CurseForge-ZIP) …"), self.import_modpack)
        imp_menu.addAction(tr("🔄  Aus anderen Launchern übernehmen …"), self.import_launchers)
        imp.clicked.connect(lambda: imp_menu.exec(imp.mapToGlobal(imp.rect().bottomLeft())))
        section.addWidget(imp)
        new = QPushButton("＋")
        new.setObjectName("iconbtn")
        new.setToolTip(tr("Neue Instanz"))
        new.clicked.connect(self.new_instance)
        section.addWidget(new)
        sl.addLayout(section)

        self.instance_list = InstanceList()
        self.instance_list.instanceActivated.connect(self.open_instance)
        self.instance_list.layoutChanged.connect(self._instance_layout_changed)
        self.instance_list.groupToggled.connect(self._toggle_group)
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
            cp.perfRequested.connect(self.performance_pack)
            cp.searchRequested.connect(self.search_for)
            cp.profileApplied.connect(self._refresh_pages)
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
        console = QPushButton("📜")
        console.setObjectName("iconbtn")
        console.setToolTip(tr("Spiel-Konsole (Live-Log)"))
        console.clicked.connect(lambda: self.show_console(self.game_instance or self._play_target()))
        bl.addWidget(console)
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
        elif key == "packs":
            self.instance_list.clearSelection()
            self.stack.setCurrentWidget(self.packs_page)
            self.packs_page.activate()
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
        if inst.group in self._collapsed():
            self._toggle_group(inst.group)
        self.instance_list.select(inst)
        self._select_instance(inst)
        self.stack.setCurrentIndex(2)
        self._update_play_label()

    # --- Reihenfolge & Ordner ----------------------------------------------
    def _collapsed(self) -> set:
        return set(self.settings.extra.get("collapsed_groups", []))

    def _groups(self) -> list:
        groups = list(self.settings.extra.get("groups", []))
        for inst in self.instances:
            if inst.group and inst.group not in groups:
                groups.append(inst.group)
        return groups

    def _sorted_instances(self, instances: list) -> list:
        order = self.settings.extra.get("instance_order", [])
        pos = {name: i for i, name in enumerate(order)}
        return sorted(instances, key=lambda i: (pos.get(i.path.name, len(pos)), i.name.lower()))

    def _fill_instance_list(self) -> None:
        self.instance_list.populate(self.instances, self._groups(), self._collapsed())
        if self.instance is not None and self.stack.currentIndex() == 2:
            self.instance_list.select(self.instance)

    def _instance_layout_changed(self, layout: list) -> None:
        by_path = {str(i.path): i for i in self.instances}
        order = []
        for key, group in layout:
            inst = by_path.get(key)
            if inst is None:
                continue
            order.append(inst.path.name)
            if inst.group != group:
                inst.group = group
                inst.save()
        self.settings.extra["instance_order"] = order
        self.settings.save()
        self.instances = self._sorted_instances(self.instances)
        self._fill_instance_list()

    def _toggle_group(self, name: str) -> None:
        collapsed = self._collapsed()
        collapsed ^= {name}
        self.settings.extra["collapsed_groups"] = sorted(collapsed)
        self.settings.save()
        self._fill_instance_list()

    def move_to_group(self, inst, group: str) -> None:
        inst.group = group
        inst.save()
        groups = self._groups()
        if group and group not in groups:
            groups.append(group)
        self.settings.extra["groups"] = groups
        self.settings.save()
        self._fill_instance_list()

    def new_group_for(self, inst) -> None:
        name, ok = QInputDialog.getText(self, tr("Neuer Ordner"), tr("Name des Ordners (z.B. Survival, Tests, Mit Freunden):"))
        if ok and name.strip():
            self.move_to_group(inst, name.strip())

    def rename_group(self, old: str) -> None:
        name, ok = QInputDialog.getText(self, tr("Ordner umbenennen"), tr("Neuer Name:"), text=old)
        if not ok or not name.strip() or name.strip() == old:
            return
        name = name.strip()
        for inst in self.instances:
            if inst.group == old:
                inst.group = name
                inst.save()
        self.settings.extra["groups"] = [name if g == old else g for g in self._groups()]
        self.settings.save()
        self._fill_instance_list()

    def remove_group(self, name: str) -> None:
        for inst in self.instances:
            if inst.group == name:
                inst.group = ""
                inst.save()
        self.settings.extra["groups"] = [g for g in self._groups() if g != name]
        self.settings.save()
        self._fill_instance_list()

    # --- Instanzen ---------------------------------------------------------
    def reload_instances(self, select: str = "", show_home: bool = False) -> None:
        self.instances = self._sorted_instances(list_instances())
        self.instance = None
        self._fill_instance_list()
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
        if inst.pack:
            chips.append((f"📦 {packs.PROVIDERS.get(inst.pack.get('provider'), '')} · {inst.pack.get('version_name', '')}",
                          "chip"))
        if inst.ram_mb:
            chips.append((f"🧠 {inst.ram_mb / 1024:.1f} GB", "chip"))
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
        self.instance_list.update_instance(inst)

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
        inst = self.instance_list.instance_at(item)
        if inst is None:
            name = item.data(Qt.ItemDataRole.UserRole + 1)
            menu = QMenu(self)
            menu.addAction(tr("✏  Ordner umbenennen …"), lambda: self.rename_group(name))
            menu.addAction(tr("📤  Ordner auflösen"), lambda: self.remove_group(name))
            menu.exec(self.instance_list.viewport().mapToGlobal(pos))
            return
        self.open_instance(inst)
        self._instance_menu().exec(self.instance_list.viewport().mapToGlobal(pos))

    def _instance_menu(self) -> QMenu:
        menu = QMenu(self)
        if not self.instance:
            return menu
        menu.addAction(tr("▶  Spielen"), lambda: self.play(self.instance))
        menu.addSeparator()
        menu.addMenu(self._icon_menu())
        groups = menu.addMenu(tr("📁  In Ordner verschieben"))
        inst = self.instance
        for g in self._groups():
            act = groups.addAction(g, lambda g=g: self.move_to_group(inst, g))
            act.setEnabled(g != inst.group)
        groups.addAction(tr("＋ Neuer Ordner …"), lambda: self.new_group_for(inst))
        if inst.group:
            groups.addSeparator()
            groups.addAction(tr("Aus Ordner entfernen"), lambda: self.move_to_group(inst, ""))
        menu.addAction(tr("✏  Umbenennen …"), self.rename_instance)
        menu.addAction(tr("⧉  Kopieren …"), self.duplicate_instance)
        menu.addAction(tr("⚙  Instanz-Einstellungen …"), self.instance_settings)
        menu.addAction(tr("📤  Als Modpack teilen …"), self.export_modpack)
        if self.instance.pack:
            menu.addAction(tr("📦  Modpack-Version ändern …"), self.change_pack_version)
        menu.addAction(tr("💾  Welt-Backups …"), lambda: WorldBackupsDialog(self.instance, self.settings, self).exec())
        menu.addAction(tr("📁  Ordner öffnen"), self.open_instance_folder)
        menu.addAction(tr("📜  Konsole / Log"), lambda: self.show_console(self.instance))
        menu.addAction(tr("🖥  Desktop-Verknüpfung erstellen"), self.create_shortcut)
        menu.addAction(tr("⭐  Optionen als Standard für neue Instanzen"), self.save_default_options)
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

    def instance_settings(self) -> None:
        if self.instance and InstanceSettingsDialog(self.instance, self.settings, self).exec():
            self.status(tr("✔ Einstellungen von „{name}“ gespeichert.").format(name=self.instance.name))
            self._update_header()

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
                ManualDownloadDialog(inst, manual, self).exec()
                self._refresh_pages()

        run_task(lambda progress: modpack.import_pack(p, self.settings, progress), done,
                 lambda err: (self._done(tr("⚠ Import fehlgeschlagen.")), QMessageBox.warning(self, tr("Import"), err)),
                 self.on_progress)

    def update_launcher(self, info: dict) -> None:
        if self.game_process is not None:
            QMessageBox.information(self, "ModNest", tr("Bitte zuerst Minecraft beenden."))
            return
        if QMessageBox.question(self, "ModNest", tr(
                "ModNest {v} herunterladen und installieren?\n\nDer Launcher startet danach automatisch neu. "
                "Deine Instanzen und Welten bleiben erhalten.").format(v=info["version"])) != QMessageBox.StandardButton.Yes:
            return

        def done(setup):
            updater.run_setup(setup)
            QApplication.instance().quit()

        run_task(lambda progress: updater.download_setup(info, progress), done,
                 lambda err: (self._done(tr("⚠ Update fehlgeschlagen.")), QMessageBox.warning(self, "ModNest", err)),
                 self.on_progress)

    # --- Komfort ------------------------------------------------------------
    def _discord_id(self) -> str:
        return self.settings.discord_client_id.strip() or DEFAULT_KEYS.get("discord_client_id", "")

    def import_launchers(self) -> None:
        dlg = ImportLaunchersDialog(self)
        if not dlg.exec():
            return
        chosen, worlds = dlg.selected(), dlg.worlds.isChecked()
        if not chosen or self._busy():
            return
        self.pack_busy = True

        def work(progress):
            latest = ""
            if any(not f.mc_version for f in chosen):
                try:
                    latest = game.release_versions()[0]
                except Exception:  # noqa: BLE001
                    latest = ""
            done, failed = [], []
            for f in chosen:
                progress(tr("Übernehme „{name}“ …").format(name=f.name), 0, 0)
                try:
                    done.append(importers.import_found(f, worlds, progress, latest))
                except Exception as exc:  # noqa: BLE001 – andere trotzdem importieren
                    failed.append(f"{f.name}: {exc}")
            return done, failed

        def finished(result):
            self.pack_busy = False
            done, failed = result
            self._done(tr("✔ {n} Instanz(en) übernommen.").format(n=len(done)))
            self.reload_instances(select=str(done[0].path) if done else "")
            if failed:
                QMessageBox.warning(self, tr("Import"), tr("Nicht übernommen:\n\n{list}").format(list="\n".join(failed)))

        run_task(work, finished, lambda err: (setattr(self, "pack_busy", False), self._done(tr("⚠ Import fehlgeschlagen.")),
                                              QMessageBox.warning(self, tr("Import"), err)), self.on_progress)

    def show_console(self, inst) -> None:
        if inst is None:
            return
        win = getattr(self, "_consoles", {}).get(str(inst.path))
        if win is None:
            win = LogWindow(inst, self)
            self._consoles = getattr(self, "_consoles", {})
            self._consoles[str(inst.path)] = win
            win.finished.connect(lambda _=0, k=str(inst.path): self._consoles.pop(k, None))
        win.show()
        win.raise_()
        win.activateWindow()

    def create_shortcut(self) -> None:
        inst = self.instance
        if not inst:
            return
        ico = shortcuts.icon_cache_dir() / f"{inst.path.name}.ico"
        try:
            save_ico(ico, instance_icon(inst, 256).pixmap(256, 256))
            link = shortcuts.create_instance_shortcut(inst, ico)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Verknüpfung"), tr("Die Verknüpfung konnte nicht erstellt werden:\n{e}").format(e=exc))
            return
        self.status(tr("✔ Verknüpfung „{name}“ liegt auf dem Desktop – ein Doppelklick startet die Instanz direkt.").format(
            name=link.stem))

    def save_default_options(self) -> None:
        inst = self.instance
        if not inst:
            return
        saved = save_defaults(inst)
        if not saved:
            QMessageBox.information(self, tr("Standard-Optionen"), tr(
                "Diese Instanz hat noch keine Einstellungen. Starte sie einmal, stell alles ein (Tasten, Sichtweite, "
                "Sprache …) und versuch es dann erneut."))
            return
        self.status(tr("✔ Neue Instanzen übernehmen ab jetzt die Einstellungen von „{name}“.").format(name=inst.name))

    def change_skin(self) -> None:
        account = self.accounts.active
        if account is None:
            return
        client_id = self.settings.ms_client_id.strip()
        store = self.accounts

        def token():
            accounts.refresh(account, client_id)
            store.save()
            return account.mc_token

        SkinDialog(account, token, self).exec()

    # --- Fertige Modpacks ---------------------------------------------------
    def _busy(self) -> bool:
        if self.installing or self.pack_busy:
            QMessageBox.information(self, tr("Bitte warten"), tr("Es wird gerade schon etwas installiert."))
            return True
        return False

    def install_pack(self, pack, version=None) -> None:
        if self._busy():
            return
        self.pack_busy = True
        settings = self.settings

        def work(progress):
            v = version
            if v is None:
                progress(tr("Suche neueste Version von {name} …").format(name=pack.name), 0, 0)
                versions = packs.provider(pack.provider).versions(pack, settings)
                if not versions:
                    raise SourceError(tr("Für dieses Modpack gibt es keine installierbare Version."))
                stable = [x for x in versions if x.release_type == "release"]
                v = next((x for x in versions if x.recommended), None) or (stable or versions)[0]
            return packs.install(pack, v, settings, progress)

        def done(inst):
            self.pack_busy = False
            self._done(tr("✔ Modpack „{name}“ installiert.").format(name=inst.name))
            self.reload_instances(select=str(inst.path))
            if inst.import_manual:
                ManualDownloadDialog(inst, inst.import_manual, self).exec()
                self._refresh_pages()

        def fail(err):
            self.pack_busy = False
            self._done(tr("⚠ Installation fehlgeschlagen."))
            QMessageBox.warning(self, tr("Modpack installieren"), err)

        self.on_progress(tr("Installiere {name} …").format(name=pack.name), 0, 0)
        run_task(work, done, fail, self.on_progress)

    def change_pack_version(self) -> None:
        inst = self.instance
        if not inst or not inst.pack:
            return
        self.on_progress(tr("Lade Modpack-Infos …"), 0, 0)

        def got(pack):
            self._done(tr("Bereit."))
            if pack is None:
                QMessageBox.warning(self, tr("Modpack"), tr("Die Herkunft dieses Modpacks ist unbekannt."))
                return
            dlg = PackVersionDialog(pack, self.settings, self.icon_loader, self,
                                    current=inst.pack.get("version_id", ""),
                                    title=tr("Modpack-Version ändern – {name}").format(name=inst.name))
            dlg.set_ok_text(tr("Zu dieser Version wechseln"))
            if dlg.exec() and dlg.selected is not None:
                self.update_pack(inst, pack, dlg.selected)

        run_task(lambda: packs.pack_from_instance(inst), got,
                 lambda err: (self._done(tr("Bereit.")), QMessageBox.warning(self, tr("Modpack"), err)))

    def update_pack(self, inst, pack, version) -> None:
        if self._busy():
            return
        if self.game_process is not None and self.game_instance is inst:
            QMessageBox.information(self, tr("Modpack"), tr("Bitte zuerst Minecraft beenden."))
            return
        question = tr("„{name}“ auf Version {version} umstellen?\n\n"
                      "Deine Welten, Einstellungen und selbst hinzugefügten Mods bleiben erhalten. "
                      "Vorher wird automatisch ein Backup der Mods und Configs angelegt.").format(
            name=inst.name, version=version.name)
        if QMessageBox.question(self, tr("Modpack aktualisieren"), question) != QMessageBox.StandardButton.Yes:
            return
        self.pack_busy = True
        settings = self.settings

        def done(updated):
            self.pack_busy = False
            self._done(tr("✔ „{name}“ ist jetzt auf Version {version}.").format(name=updated.name, version=version.name))
            self.reload_instances(select=str(updated.path))
            if updated.import_manual:
                ManualDownloadDialog(updated, updated.import_manual, self).exec()
                self._refresh_pages()

        def fail(err):
            self.pack_busy = False
            self._done(tr("⚠ Update fehlgeschlagen."))
            QMessageBox.warning(self, tr("Modpack aktualisieren"), tr(
                "{e}\n\nEin Backup deiner Mods und Configs liegt im Backup-Ordner unter „Modpack-Updates“.").format(e=err))

        self.on_progress(tr("Aktualisiere {name} …").format(name=inst.name), 0, 0)
        run_task(lambda progress: packs.update(inst, pack, version, settings, progress), done, fail, self.on_progress)

    def _refresh_pages(self) -> None:
        if self.instance:
            self.instance.sync_with_disk()
            for page in self.pages.values():
                page.refresh()

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
            menu.addAction(tr("👕  Skin & Umhang …"), self.change_skin)
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

    def performance_pack(self) -> None:
        inst = self.instance
        if not inst:
            return
        dlg = PerfDialog(inst, self)
        if not dlg.exec():
            return
        names = inst.content["mods"].category_names()
        category = "Performance" if "Performance" in names else None
        for opt in dlg.selected():
            self.queue_install(opt.project, category, opt.release, instance=inst, pin=False)

    def show_changelog(self, upd) -> None:
        title = tr("Was ist neu? – {name} {version}").format(name=upd.item.name, version=upd.release.version_name)
        if upd.release.changelog or upd.item.source != "curseforge":
            ChangelogDialog(title, upd.release.changelog, self).exec()
            return
        settings = self.settings

        def work():
            resp = modrinth.session.get(
                f"https://api.curseforge.com/v1/mods/{upd.item.project_id}/files/{upd.release.version_id}/changelog",
                headers={"x-api-key": settings.curseforge_api_key.strip()}, timeout=20)
            resp.raise_for_status()
            return resp.json().get("data", "")

        self.status(tr("Lade Changelog …"))
        run_task(work, lambda html: (self._done(tr("Bereit.")), ChangelogDialog(title, html, self, markdown=False).exec()),
                 lambda err: (self._done(tr("Bereit.")), ChangelogDialog(title, "", self).exec()))

    def search_for(self, query: str) -> None:
        """Öffnet „Entdecken“ mit einem Suchbegriff (z.B. eine fehlende Abhängigkeit)."""
        self.tabs.setCurrentWidget(self.search_page)
        self.search_page.set_kind("mods")
        self.search_page.query.setText(query)
        self.search_page.search()

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
        if not self.install_queue and not self.installing:
            self._quick_compat(inst)

    def _quick_compat(self, inst) -> None:
        """Prüft nach Installationen still im Hintergrund und meldet nur echte Probleme."""
        def done(issues):
            errors = [i for i in issues if i.severity == "error"]
            if errors:
                self.status(tr("⚠ {n} Problem(e) in „{name}“ gefunden: {first} – Details unter Mods → 🩺 Prüfen").format(
                    n=len(errors), name=inst.name, first=errors[0].title))
        run_task(lambda: compat.check(inst), done, lambda err: None)

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
            if self.settings.discord_rpc:
                discord_rpc.set_playing(self._discord_id(), inst.name,
                                        f"{LOADERS.get(inst.loader, inst.loader)} {inst.mc_version}",
                                        quick_play[1] if quick_play and quick_play[0] == "server" else "")
            if self.settings.minimize_on_launch:
                self.showMinimized()

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
        discord_rpc.clear(self._discord_id())
        if self.isMinimized():
            self.showNormal()
            self.activateWindow()
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
