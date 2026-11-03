"""Hauptfenster: Instanzliste links, Mods/Texturepacks/Shader/Entdecken in der Mitte, Spielen-Leiste unten."""
import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .. import accounts, game, installer
from ..config import APP_NAME, APP_VERSION
from ..instances import KINDS, LOADERS, create_instance, delete_instance, list_instances
from ..sources import modrinth
from .content_page import ContentPage
from .dialogs import NewInstanceDialog, SettingsDialog
from .icons import app_icon, instance_avatar, logo_pixmap
from .login_dialog import MicrosoftLoginDialog
from .search_page import SearchPage
from .version_dialog import VersionDialog
from .workers import IconLoader, run_task

TAB_ICONS = {"mods": "🧩", "resourcepacks": "🎨", "shaderpacks": "✨"}


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.instances = []
        self.instance = None
        self.install_queue = []
        self.installing = False
        self.game_process = None
        self.icon_loader = IconLoader(self)
        self.accounts = accounts.AccountStore()
        if not self.accounts.accounts:
            # Erster Start: Offline-Konto aus dem bisherigen Spielernamen anlegen
            self.accounts.add(accounts.offline_account(settings.username or "Steve"))

        self.setWindowTitle(f"{APP_NAME} Launcher")
        self.setWindowIcon(app_icon())
        self.resize(1240, 800)
        self.setMinimumSize(980, 640)

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

        # --- Seitenleiste --------------------------------------------------
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(264)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 18, 16, 16)
        sl.setSpacing(8)
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

        section = QHBoxLayout()
        lbl = QLabel("INSTANZEN")
        lbl.setObjectName("section")
        section.addWidget(lbl, 1)
        add_btn = QPushButton("＋")
        add_btn.setObjectName("iconbtn")
        add_btn.setToolTip("Neue Instanz")
        add_btn.clicked.connect(self.new_instance)
        section.addWidget(add_btn)
        sl.addLayout(section)

        self.instance_list = QListWidget()
        self.instance_list.setObjectName("instances")
        self.instance_list.setIconSize(QSize(38, 38))
        self.instance_list.currentRowChanged.connect(self._select_instance)
        self.instance_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.instance_list.customContextMenuRequested.connect(self._instance_menu)
        sl.addWidget(self.instance_list, 1)

        new_btn = QPushButton("＋  Neue Instanz")
        new_btn.setObjectName("ghost")
        new_btn.clicked.connect(self.new_instance)
        sl.addWidget(new_btn)
        settings_btn = QPushButton("⚙  Einstellungen")
        settings_btn.setObjectName("ghost")
        settings_btn.clicked.connect(self.open_settings)
        sl.addWidget(settings_btn)
        body.addWidget(side)

        # --- Inhalt --------------------------------------------------------
        content = QWidget()
        content.setObjectName("content")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(28, 22, 28, 14)
        cl.setSpacing(4)

        header = QHBoxLayout()
        self.header_icon = QLabel()
        self.header_icon.setFixedSize(56, 56)
        header.addWidget(self.header_icon)
        header.addSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(6)
        self.title = QLabel("Keine Instanz")
        self.title.setObjectName("title")
        titles.addWidget(self.title)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        titles.addLayout(self.chips)
        header.addLayout(titles, 1)
        for text, tip, slot in [("📁", "Instanz-Ordner öffnen", self.open_instance_folder),
                                ("🗑", "Instanz löschen", self.delete_instance)]:
            btn = QPushButton(text)
            btn.setObjectName("iconbtn")
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            header.addWidget(btn)
        cl.addLayout(header)
        cl.addSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.pages: dict[str, ContentPage] = {}
        for kind in KINDS:
            page = ContentPage(kind, self.icon_loader)
            page.message.connect(self.status)
            page.versionRequested.connect(self.change_version)
            page.irisRequested.connect(self.install_iris)
            self.pages[kind] = page
            self.tabs.addTab(page, f"{TAB_ICONS[kind]}  {KINDS[kind]['label']}")
        self.search_page = SearchPage(settings, self.icon_loader)
        self.search_page.message.connect(self.status)
        self.search_page.installRequested.connect(self.queue_install)
        self.search_page.versionPickRequested.connect(self.pick_version_for_install)
        self.tabs.addTab(self.search_page, "🔍  Entdecken")
        self.tabs.currentChanged.connect(self._tab_changed)
        cl.addWidget(self.tabs, 1)
        body.addWidget(content, 1)

        # --- Spielen-Leiste ------------------------------------------------
        bar = QWidget()
        bar.setObjectName("playbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(24, 14, 24, 14)
        bl.setSpacing(14)
        status_col = QVBoxLayout()
        status_col.setSpacing(6)
        self.status_label = QLabel("Bereit.")
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
        self.play_btn = QPushButton("▶   SPIELEN")
        self.play_btn.setObjectName("play")
        glow = QGraphicsDropShadowEffect(self.play_btn)
        glow.setBlurRadius(28)
        glow.setOffset(0, 4)
        glow.setColor(QColor(16, 185, 129, 110))
        self.play_btn.setGraphicsEffect(glow)
        self.play_btn.clicked.connect(self.play)
        bl.addWidget(self.play_btn)
        outer.addWidget(bar)

        self.game_timer = QTimer(self)
        self.game_timer.timeout.connect(self._check_game)
        self._update_account()
        self.reload_instances(select=settings.last_instance)

    # --- Instanzen ---------------------------------------------------------
    def reload_instances(self, select: str = "") -> None:
        self.instances = list_instances()
        self.instance_list.blockSignals(True)
        self.instance_list.clear()
        for inst in self.instances:
            item = QListWidgetItem(instance_avatar(inst.name, inst.loader, 38),
                                   f"{inst.name}\n{LOADERS.get(inst.loader, inst.loader)} · {inst.mc_version}")
            item.setSizeHint(QSize(0, 58))
            self.instance_list.addItem(item)
        self.instance_list.blockSignals(False)
        idx = next((i for i, inst in enumerate(self.instances) if str(inst.path) == select), 0)
        if self.instances:
            self.instance_list.setCurrentRow(idx)
            self._select_instance(idx)
        else:
            self._select_instance(-1)

    def _select_instance(self, row: int) -> None:
        self.instance = self.instances[row] if 0 <= row < len(self.instances) else None
        if self.instance:
            self.settings.last_instance = str(self.instance.path)
            self.settings.save()
        for page in self.pages.values():
            page.set_instance(self.instance)
        self.search_page.set_instance(self.instance)
        self.play_btn.setEnabled(self.instance is not None)
        self._update_header()

    def _update_header(self) -> None:
        while self.chips.count():
            w = self.chips.takeAt(0).widget()
            if w:
                w.deleteLater()
        inst = self.instance
        if not inst:
            self.title.setText("Willkommen bei ModNest")
            self.header_icon.setPixmap(logo_pixmap(56))
            chip = QLabel("Lege links eine neue Instanz an, um loszulegen.")
            chip.setObjectName("hint")
            self.chips.addWidget(chip)
            self.chips.addStretch(1)
            for i in range(len(KINDS)):
                self.tabs.setTabText(i, f"{TAB_ICONS[list(KINDS)[i]]}  {list(KINDS.values())[i]['label']}")
            return
        self.title.setText(inst.name)
        self.header_icon.setPixmap(instance_avatar(inst.name, inst.loader, 56).pixmap(56, 56))
        for text, name in [(f"Minecraft {inst.mc_version}", "chip"),
                           (LOADERS.get(inst.loader, inst.loader), "chipaccent")]:
            chip = QLabel(text)
            chip.setObjectName(name)
            self.chips.addWidget(chip)
        for kind, info in KINDS.items():
            count = len(inst.content[kind].items)
            if count:
                chip = QLabel(f"{count} {info['singular'] if count == 1 else info['label']}")
                chip.setObjectName("chip")
                self.chips.addWidget(chip)
        self.chips.addStretch(1)
        for i, (kind, info) in enumerate(KINDS.items()):
            count = len(inst.content[kind].items)
            self.tabs.setTabText(i, f"{TAB_ICONS[kind]}  {info['label']}" + (f"  {count}" if count else ""))

    def _tab_changed(self, index: int) -> None:
        page = self.tabs.widget(index)
        if isinstance(page, ContentPage):
            page.refresh()
            self.search_page.set_kind(page.kind)
        else:
            self.search_page.refresh_categories()
        self._update_header()

    def _instance_menu(self, pos) -> None:
        if not self.instance:
            return
        menu = QMenu(self)
        menu.addAction("📁  Ordner öffnen", self.open_instance_folder)
        menu.addAction("✏  Umbenennen …", self.rename_instance)
        menu.addSeparator()
        menu.addAction("🗑  Löschen …", self.delete_instance)
        menu.exec(self.instance_list.viewport().mapToGlobal(pos))

    def new_instance(self) -> None:
        dlg = NewInstanceDialog(self)
        if dlg.exec():
            name, version, loader = dlg.values()
            if not name or not version or " " in version:
                QMessageBox.warning(self, "Neue Instanz", "Bitte Name und eine gültige Minecraft-Version angeben.")
                return
            inst = create_instance(name, version, loader)
            self.reload_instances(select=str(inst.path))

    def rename_instance(self) -> None:
        name, ok = QInputDialog.getText(self, "Instanz umbenennen", "Neuer Name:", text=self.instance.name)
        if ok and name.strip():
            self.instance.name = name.strip()
            self.instance.save()
            self.reload_instances(select=str(self.instance.path))

    def open_instance_folder(self) -> None:
        if self.instance:
            os.startfile(self.instance.path)  # noqa: S606

    def delete_instance(self) -> None:
        if not self.instance:
            return
        if QMessageBox.question(self, "Instanz löschen",
                                f"„{self.instance.name}“ inklusive aller Mods und Welten löschen?") \
                == QMessageBox.StandardButton.Yes:
            delete_instance(self.instance)
            self.reload_instances()

    def open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec():
            self._update_account()
            self.status("Einstellungen gespeichert.")

    # --- Konten ------------------------------------------------------------
    def _update_account(self) -> None:
        acc = self.accounts.active
        icon = "🟢" if acc and acc.kind == "microsoft" else "👤"
        self.account_btn.setText(f"{icon}  {acc.label if acc else 'Kein Konto'}   ")

    def _fill_account_menu(self) -> None:
        menu = self.account_menu
        menu.clear()
        active = self.accounts.active
        for acc in self.accounts.accounts:
            action = menu.addAction(acc.label, lambda a=acc: self._switch_account(a))
            action.setCheckable(True)
            action.setChecked(active is not None and acc.id == active.id)
        menu.addSeparator()
        menu.addAction("➕ Microsoft-Konto hinzufügen …", self.add_microsoft_account)
        menu.addAction("➕ Offline-Konto hinzufügen …", self.add_offline_account)
        if active:
            menu.addSeparator()
            menu.addAction(f"Abmelden: {active.name}", lambda: self._remove_account(active))

    def _switch_account(self, acc) -> None:
        self.accounts.set_active(acc)
        self._update_account()

    def add_microsoft_account(self) -> None:
        if not self.settings.ms_client_id.strip():
            QMessageBox.information(
                self, "Microsoft-Login",
                "Für den Microsoft-Login wird eine Azure Client-ID benötigt.\n\n"
                "Trag sie unter ⚙ Einstellungen ein. Wie du sie bekommst, steht in der README.")
            self.open_settings()
            if not self.settings.ms_client_id.strip():
                return
        dlg = MicrosoftLoginDialog(self.settings, self)
        if dlg.exec() and dlg.account:
            self.accounts.add(dlg.account)
            self._update_account()
            self.status(f"✔ Angemeldet als {dlg.account.name}.")

    def add_offline_account(self) -> None:
        name, ok = QInputDialog.getText(self, "Offline-Konto", "Spielername (3–16 Zeichen, A–Z, 0–9, _):")
        name = name.strip()
        if not ok or not name:
            return
        if not (3 <= len(name) <= 16) or not all(c.isascii() and (c.isalnum() or c == "_") for c in name):
            QMessageBox.warning(self, "Offline-Konto", "Ungültiger Name. Erlaubt sind 3–16 Zeichen: A–Z, 0–9 und _.")
            return
        self.accounts.add(accounts.offline_account(name))
        self._update_account()

    def _remove_account(self, acc) -> None:
        if QMessageBox.question(self, "Abmelden", f"Konto „{acc.label}“ aus dem Launcher entfernen?") \
                == QMessageBox.StandardButton.Yes:
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

    # --- Installieren & Versionen ------------------------------------------
    def queue_install(self, project, category, release=None) -> None:
        if not self.instance:
            return
        self.install_queue.append((self.instance, project, category, release))
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

    def install_iris(self) -> None:
        self.status("Suche Iris auf Modrinth …")
        run_task(lambda: modrinth.get_project("iris", "mods"),
                 lambda proj: self.queue_install(proj, None, None),
                 lambda err: self._done(f"⚠ Iris konnte nicht gefunden werden: {err}"))

    def _next_install(self) -> None:
        if self.installing or not self.install_queue:
            return
        self.installing = True
        inst, project, category, release = self.install_queue.pop(0)

        def work(progress):
            return installer.install_project(inst, project, self.settings, category, progress, release)

        def done(names):
            self.installing = False
            extra = f" (+ {len(names) - 1} Abhängigkeit(en))" if len(names) > 1 else ""
            version = f" in Version {release.version_name}" if release else ""
            self._done(f"✔ {project.title}{version} installiert{extra}.")
            self._after_install(inst)

        def fail(err):
            self.installing = False
            self._done(f"⚠ {project.title}: Installation fehlgeschlagen.")
            QMessageBox.warning(self, "Installation fehlgeschlagen", f"{project.title}:\n\n{err}")
            self._after_install(inst)

        run_task(work, done, fail, self.on_progress)

    def _after_install(self, inst) -> None:
        if inst is self.instance:
            for page in self.pages.values():
                page.refresh()
            self.search_page.mark_installed()
            self._update_header()
        self._next_install()

    # --- Spielen -----------------------------------------------------------
    def play(self) -> None:
        if not self.instance or self.game_process is not None:
            return
        if self.installing:
            QMessageBox.information(self, "Bitte warten", "Es werden gerade noch Inhalte installiert.")
            return
        account = self.accounts.active
        if account is None:
            QMessageBox.information(self, "Kein Konto", "Bitte zuerst über den Konto-Button ein Konto hinzufügen.")
            return
        inst = self.instance
        store = self.accounts
        client_id = self.settings.ms_client_id.strip()
        self.play_btn.setEnabled(False)
        self.play_btn.setText("Startet …")

        def work(progress):
            if account.kind == "microsoft":
                progress(f"Melde {account.name} bei Microsoft an …", 0, 0)
                accounts.refresh(account, client_id)
            inst.write_resourcepack_order()
            return game.launch(inst, self.settings, account, progress)

        def done(proc):
            store.save()          # ggf. neuer Refresh-Token
            self._update_account()
            self.game_process = proc
            self.play_btn.setText("●   LÄUFT")
            self._done(f"Minecraft läuft ({inst.name}). Log: launcher-log.txt im Instanz-Ordner.")
            self.game_timer.start(2000)

        def fail(err):
            self._reset_play()
            self._done("⚠ Start fehlgeschlagen.")
            QMessageBox.critical(self, "Start fehlgeschlagen", err)

        run_task(work, done, fail, self.on_progress)

    def _check_game(self) -> None:
        if self.game_process and self.game_process.poll() is not None:
            code = self.game_process.returncode
            self.game_process = None
            self.game_timer.stop()
            self._reset_play()
            self.status("Minecraft wurde beendet." if code == 0 else
                        f"⚠ Minecraft wurde mit Code {code} beendet – siehe launcher-log.txt im Instanz-Ordner.")

    def _reset_play(self) -> None:
        self.play_btn.setText("▶   SPIELEN")
        self.play_btn.setEnabled(self.instance is not None)

    def closeEvent(self, event) -> None:
        for page in self.pages.values():
            if page.instance:
                page.save_layout()
        super().closeEvent(event)
