"""Dialoge: neue Instanz, Instanz kopieren, Icon wählen, Einstellungen."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget,
)

from .. import backup, game, java
from ..i18n import LANGUAGES, tr
from ..instances import KINDS, LOADERS, clear_defaults, has_defaults
from ..system import ram_rating, total_ram_mb
from .workers import run_task


class NewInstanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Neue Instanz"))
        self.setMinimumWidth(420)
        form = QFormLayout(self)

        self.name = QLineEdit(tr("Mein Modpack"))
        form.addRow(tr("Name"), self.name)

        self.version = QComboBox()
        self.version.setEditable(True)
        self.version.addItem(tr("Lade Versionen …"))
        self.snapshots = QCheckBox(tr("Snapshots anzeigen"))
        self.snapshots.toggled.connect(self._load_versions)
        row = QHBoxLayout()
        row.addWidget(self.version, 1)
        row.addWidget(self.snapshots)
        wrap = QWidget()
        wrap.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        form.addRow("Minecraft", wrap)

        self.loader = QComboBox()
        for key, label in LOADERS.items():
            self.loader.addItem(label, key)
        self.loader.setCurrentIndex(1)  # Fabric
        form.addRow(tr("Mod-Loader"), self.loader)

        hint = QLabel(tr("Tipp: Fabric hat die meisten Performance-Mods (Sodium, Lithium …)."))
        hint.setObjectName("hint")
        form.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._load_versions()

    def _load_versions(self):
        include = self.snapshots.isChecked()
        run_task(lambda: game.release_versions(include), self._fill_versions,
                 lambda err: self.version.setItemText(0, tr("Offline? Version manuell eingeben")))

    def _fill_versions(self, versions):
        try:
            self.version.clear()
            self.version.addItems(versions)
        except RuntimeError:
            pass  # Dialog schon geschlossen

    def values(self) -> tuple[str, str, str]:
        return self.name.text().strip(), self.version.currentText().strip(), self.loader.currentData()


class DuplicateDialog(QDialog):
    """Instanz kopieren: neuer Name, optional mit Welten und Screenshots."""

    def __init__(self, instance, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Instanz kopieren"))
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.name = QLineEdit(tr("{name} (Kopie)").format(name=instance.name))
        form.addRow(tr("Name der Kopie"), self.name)
        self.worlds = QCheckBox(tr("Welten mitkopieren"))
        self.worlds.setChecked(True)
        form.addRow(self.worlds)
        self.screens = QCheckBox(tr("Screenshots mitkopieren"))
        form.addRow(self.screens)
        hint = QLabel(tr("Mods, Texturepacks, Shader, Kategorien und Configs werden immer mitkopiert."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Kopieren"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class IconPickerDialog(QDialog):
    """Wählt das Icon eines installierten Mods/Packs als Instanz-Icon."""

    def __init__(self, instance, icon_loader, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Icon aus installierten Inhalten wählen"))
        self.resize(560, 440)
        self.pixmap = None
        self._pixmaps = {}
        layout = QVBoxLayout(self)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(64, 64))
        self.grid.setGridSize(QSize(108, 108))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setWordWrap(True)
        self.grid.itemDoubleClicked.connect(lambda *_: self._accept())
        layout.addWidget(self.grid, 1)
        seen = set()
        for kind in KINDS:
            for item in instance.content[kind].items:
                if not item.icon_url or item.icon_url in seen:
                    continue
                seen.add(item.icon_url)
                entry = QListWidgetItem(item.name)
                entry.setData(Qt.ItemDataRole.UserRole, item.icon_url)
                self.grid.addItem(entry)
                icon_loader.load(item.icon_url, lambda pix, e=entry, u=item.icon_url: self._loaded(e, u, pix))
        if not seen:
            empty = QLabel(tr("Noch keine Inhalte mit Icon installiert."))
            empty.setObjectName("hint")
            layout.addWidget(empty)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _loaded(self, entry, url, pix):
        self._pixmaps[url] = pix
        entry.setIcon(QIcon(pix))

    def _accept(self):
        items = self.grid.selectedItems()
        if items:
            self.pixmap = self._pixmaps.get(items[0].data(Qt.ItemDataRole.UserRole))
            if self.pixmap is not None:
                self.accept()


class RamSlider(QWidget):
    """Schieberegler für den Arbeitsspeicher mit Farbbewertung."""

    STEP = 512

    def __init__(self, value_mb: int, parent=None):
        super().__init__(parent)
        self.total = total_ram_mb()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1024 // self.STEP, max(self.total // self.STEP, 4))
        self.slider.setPageStep(2)
        self.slider.setValue(max(min(value_mb, self.total), 1024) // self.STEP)
        self.slider.valueChanged.connect(self._update)
        row.addWidget(self.slider, 1)
        self.value_label = QLabel()
        self.value_label.setObjectName("ramvalue")
        self.value_label.setMinimumWidth(70)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.value_label)
        layout.addLayout(row)
        self.rating = QLabel()
        self.rating.setWordWrap(True)
        layout.addWidget(self.rating)
        info = QLabel(tr("In deinem PC stecken {gb} GB Arbeitsspeicher.").format(gb=f"{self.total / 1024:.1f}"))
        info.setObjectName("hint")
        layout.addWidget(info)
        self._update()

    def value(self) -> int:
        return self.slider.value() * self.STEP

    def _update(self):
        mb = self.value()
        self.value_label.setText(f"{mb / 1024:.1f} GB")
        color, text = ram_rating(mb, self.total)
        self.rating.setText(f'<span style="color:{color}">●</span>  {text}')


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Einstellungen"))
        self.setMinimumWidth(600)
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)

        # --- Allgemein -----------------------------------------------------
        gen_tab = QWidget()
        form = QFormLayout(gen_tab)
        self.theme = QComboBox()
        for key, label in (("dark", tr("🌙  Dunkel")), ("light", tr("☀  Hell")), ("neon", tr("💜  Neon")), ("system", tr("🖥  Wie Windows"))):
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(max(self.theme.findData(settings.theme), 0))
        form.addRow(tr("Design"), self.theme)
        self.accent = AccentPicker(settings.accent)
        form.addRow(tr("Akzentfarbe"), self.accent)
        self.language = QComboBox()
        for key, label in LANGUAGES.items():
            self.language.addItem(label, key)
        self.language.setCurrentIndex(max(self.language.findData(settings.language), 0))
        form.addRow(tr("Sprache / Language"), self.language)
        lang_hint = QLabel(tr("Die Sprache wird nach einem Neustart des Launchers übernommen."))
        lang_hint.setObjectName("hint")
        form.addRow(lang_hint)
        self.minimize = QCheckBox(tr("Launcher beim Spielen minimieren (kommt nach dem Spiel zurück)"))
        self.minimize.setChecked(settings.minimize_on_launch)
        form.addRow(self.minimize)
        self.discord = QCheckBox(tr("In Discord anzeigen, was ich spiele"))
        self.discord.setChecked(settings.discord_rpc)
        form.addRow(self.discord)
        self.tray = QCheckBox(tr("Symbol im Infobereich der Taskleiste (unten rechts)"))
        self.tray.setChecked(settings.tray_icon)
        form.addRow(self.tray)
        self.close_tray = QCheckBox(tr("Beim Schließen dort weiterlaufen statt beenden"))
        self.close_tray.setChecked(settings.close_to_tray)
        self.close_tray.setEnabled(settings.tray_icon)
        self.tray.toggled.connect(self.close_tray.setEnabled)
        form.addRow(self.close_tray)
        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        storage_btn = QPushButton(tr("💽  Speicherplatz & Aufräumen …").replace("&", "&&"))
        storage_btn.clicked.connect(self._storage)
        tools.addWidget(storage_btn)
        self.defaults_btn = QPushButton(tr("Standard-Optionen zurücksetzen"))
        self.defaults_btn.setToolTip(tr("Neue Instanzen starten dann wieder mit den Minecraft-Standardeinstellungen."))
        self.defaults_btn.setVisible(has_defaults())
        self.defaults_btn.clicked.connect(self._clear_defaults)
        tools.addWidget(self.defaults_btn)
        tools.addStretch(1)
        tools_w = QWidget()
        tools_w.setLayout(tools)
        form.addRow(tools_w)
        self.tabs.addTab(gen_tab, tr("🎨  Allgemein"))

        # --- Spiel ---------------------------------------------------------
        game_tab = QWidget()
        form = QFormLayout(game_tab)
        self.ram = RamSlider(settings.ram_mb)
        form.addRow(tr("Arbeitsspeicher"), self.ram)
        self.java = QLineEdit(settings.java_path)
        self.java.setPlaceholderText(tr("leer = automatisch (Mojang-Java wird heruntergeladen)"))
        browse = QPushButton("…")
        browse.setFixedWidth(36)
        browse.clicked.connect(self._browse_java)
        javas = QPushButton(tr("☕ Verwalten …"))
        javas.clicked.connect(lambda: _pick_java(self, self.java))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.java, 1)
        row.addWidget(browse)
        row.addWidget(javas)
        wrap = QWidget()
        wrap.setLayout(row)
        form.addRow(tr("Java"), wrap)
        self.tabs.addTab(game_tab, tr("🎮  Spiel"))

        # --- Konten & Dienste ----------------------------------------------
        acc_tab = QWidget()
        form = QFormLayout(acc_tab)
        self.cf_key = QLineEdit("" if settings.is_builtin("curseforge_api_key") else settings.curseforge_api_key)
        self.cf_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cf_key.setPlaceholderText(tr("von console.curseforge.com"))
        if settings.builtin("curseforge_api_key"):
            self.cf_key.setPlaceholderText(tr("✔ eingebaut – nur ausfüllen, wenn du einen eigenen nutzen willst"))
        form.addRow(tr("CurseForge API-Key"), self.cf_key)
        hint = QLabel(tr('Den kostenlosen Key bekommst du auf <a href="https://console.curseforge.com">'
                      "console.curseforge.com</a> → API Keys."))
        hint.setOpenExternalLinks(True)
        hint.setObjectName("hint")
        form.addRow(hint)
        self.ms_client = QLineEdit("" if settings.is_builtin("ms_client_id") else settings.ms_client_id)
        self.ms_client.setPlaceholderText(tr("Anwendungs-ID (Client-ID) deiner Azure-App"))
        if settings.builtin("ms_client_id"):
            self.ms_client.setPlaceholderText(tr("✔ eingebaut – nur ausfüllen, wenn du eine eigene nutzen willst"))
        form.addRow(tr("Microsoft Client-ID"), self.ms_client)
        ms_hint = QLabel(tr("Für den Microsoft-Login brauchst du eine eigene, von Microsoft freigeschaltete "
                         "Azure-App – Anleitung in der README."))
        ms_hint.setWordWrap(True)
        ms_hint.setObjectName("hint")
        form.addRow(ms_hint)
        self.discord_id = QLineEdit("" if settings.is_builtin("discord_client_id") else settings.discord_client_id)
        self.discord_id.setPlaceholderText(tr("optional – Anwendungs-ID von discord.com/developers"))
        form.addRow(tr("Discord-ID"), self.discord_id)
        self.tabs.addTab(acc_tab, tr("🔑  Konten && Dienste"))

        # --- Backups -------------------------------------------------------
        bak_tab = QWidget()
        form = QFormLayout(bak_tab)
        self.backup_dir = QLineEdit(settings.backup_dir)
        self.backup_dir.setPlaceholderText(str(backup.backup_root(settings)) if not settings.backup_dir else "")
        browse_bak = QPushButton("…")
        browse_bak.setFixedWidth(36)
        browse_bak.clicked.connect(self._browse_backup)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.backup_dir, 1)
        row.addWidget(browse_bak)
        wrap = QWidget()
        wrap.setLayout(row)
        form.addRow(tr("Backup-Ordner"), wrap)
        clouds = backup.detect_cloud_folders()
        if clouds:
            cloud_row = QHBoxLayout()
            cloud_row.setContentsMargins(0, 0, 0, 0)
            cloud_row.addWidget(QLabel(tr("☁ In die Cloud:")))
            for name, path in clouds:
                btn = QPushButton(name)
                btn.setObjectName("small")
                btn.setToolTip(str(path / "ModNest Backups"))
                btn.clicked.connect(lambda _=False, p=path: self.backup_dir.setText(str(p / "ModNest Backups")))
                cloud_row.addWidget(btn)
            cloud_row.addStretch(1)
            cw = QWidget()
            cw.setLayout(cloud_row)
            form.addRow(cw)
            cloud_hint = QLabel(tr("Liegt der Backup-Ordner in deinem Cloud-Ordner, lädt das Cloud-Programm "
                                   "die Backups automatisch hoch."))
        else:
            cloud_hint = QLabel(tr("Kein Cloud-Ordner gefunden. Installiere z.B. OneDrive, Dropbox, iCloud oder "
                                   "Google Drive für Windows und wähle dessen Ordner als Backup-Ordner."))
        cloud_hint.setObjectName("hint")
        cloud_hint.setWordWrap(True)
        form.addRow(cloud_hint)
        self.bak_worlds = QCheckBox(tr("Gespielte Welten nach dem Spielen automatisch sichern"))
        self.bak_worlds.setChecked(settings.backup_worlds)
        form.addRow(self.bak_worlds)
        self.bak_keep = QSpinBox()
        self.bak_keep.setRange(1, 100)
        self.bak_keep.setValue(settings.backup_keep)
        self.bak_keep.setSuffix(tr(" Backups pro Welt"))
        form.addRow(tr("Aufbewahren"), self.bak_keep)
        self.bak_screens = QCheckBox(tr("Neue Screenshots automatisch sichern"))
        self.bak_screens.setChecked(settings.backup_screenshots)
        form.addRow(self.bak_screens)
        self.bak_updates = QCheckBox(tr("Vor Mod- und Modpack-Updates die Instanz sichern (ohne Welten)"))
        self.bak_updates.setChecked(settings.backup_before_updates)
        form.addRow(self.bak_updates)
        self.tabs.addTab(bak_tab, tr("💾  Backups"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _browse_java(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("java.exe auswählen"), "",
                                              tr("Java (java.exe javaw.exe);;Alle Dateien (*)"))
        if path:
            self.java.setText(path)

    def _storage(self):
        from .comfort_dialogs import StorageDialog
        from ..instances import list_instances
        StorageDialog(list_instances(), self.settings, self).exec()

    def _clear_defaults(self):
        clear_defaults()
        self.defaults_btn.hide()

    def _browse_backup(self):
        path = QFileDialog.getExistingDirectory(self, tr("Backup-Ordner wählen"), self.backup_dir.text())
        if path:
            self.backup_dir.setText(path)

    def _save(self):
        s = self.settings
        self.language_changed = s.language != self.language.currentData()
        s.theme = self.theme.currentData()
        s.accent = self.accent.value()
        s.language = self.language.currentData()
        s.backup_dir = self.backup_dir.text().strip()
        s.backup_worlds = self.bak_worlds.isChecked()
        s.backup_keep = self.bak_keep.value()
        s.backup_screenshots = self.bak_screens.isChecked()
        s.backup_before_updates = self.bak_updates.isChecked()
        s.ram_mb = self.ram.value()
        s.java_path = self.java.text().strip()
        s.set_key("curseforge_api_key", self.cf_key.text())
        s.set_key("ms_client_id", self.ms_client.text())
        s.set_key("discord_client_id", self.discord_id.text())
        s.minimize_on_launch = self.minimize.isChecked()
        s.tray_icon = self.tray.isChecked()
        s.close_to_tray = self.close_tray.isChecked() and s.tray_icon
        s.discord_rpc = self.discord.isChecked()
        s.save()
        self.accept()


def _pick_java(parent, line_edit, mc_version: str = "") -> None:
    dlg = JavaDialog(mc_version, parent)
    if dlg.exec():
        line_edit.setText(dlg.selected)


class JavaDialog(QDialog):
    """Gefundene Java-Versionen anzeigen, eine auswählen oder Eclipse Temurin herunterladen."""

    def __init__(self, mc_version: str = "", parent=None):
        super().__init__(parent)
        self.selected = ""
        self.setWindowTitle(tr("☕ Java-Versionen"))
        self.resize(760, 440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        text = tr("Normalerweise lädt Minecraft sein passendes Java selbst – das ist die beste Wahl.")
        if mc_version:
            text += " " + tr("Minecraft {mc} braucht Java {v}.").format(mc=mc_version, v=java.recommended_major(mc_version))
        hint = QLabel(text)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem
        self._item_cls = QTreeWidgetItem
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Version"), tr("Quelle"), tr("Pfad")])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(lambda *_: self._choose())
        lay.addWidget(self.tree, 1)
        dl = QHBoxLayout()
        dl.addWidget(QLabel(tr("Eclipse Temurin herunterladen:")))
        self.feature = QComboBox()
        dl.addWidget(self.feature)
        self.dl_btn = QPushButton(tr("⬇ Herunterladen"))
        self.dl_btn.clicked.connect(self._download)
        dl.addWidget(self.dl_btn)
        dl.addStretch(1)
        lay.addLayout(dl)
        self.status = QLabel(tr("Suche Java …"))
        self.status.setObjectName("hint")
        lay.addWidget(self.status)
        buttons = QHBoxLayout()
        auto = QPushButton(tr("Automatisch (empfohlen)"))
        auto.clicked.connect(lambda: (setattr(self, "selected", ""), self.accept()))
        buttons.addWidget(auto)
        buttons.addStretch(1)
        cancel = QPushButton(tr("Abbrechen"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        choose = QPushButton(tr("Auswählen"))
        choose.setObjectName("primary")
        choose.clicked.connect(self._choose)
        buttons.addWidget(choose)
        lay.addLayout(buttons)
        self.recommended = java.recommended_major(mc_version) if mc_version else 0
        self._load()
        run_task(java.available_features, self._features, lambda err: self._features([8, 17, 21, 25]))

    def _safe(self, fn) -> None:
        try:
            fn()
        except RuntimeError:
            pass

    def _load(self) -> None:
        run_task(java.find_all, lambda res: self._safe(lambda: self._fill(res)),
                 lambda err: self._safe(lambda: self.status.setText(f"⚠ {err}")))

    def _fill(self, javas) -> None:
        self.javas = javas
        self.tree.clear()
        for j in javas:
            mark = "  ★" if self.recommended and j.major == self.recommended else ""
            self.tree.addTopLevelItem(self._item_cls([j.version + mark, j.source, str(j.path)]))
        for col in (0, 1):
            self.tree.resizeColumnToContents(col)
        self.status.setText(tr("{n} Java-Version(en) gefunden.").format(n=len(javas)))

    def _features(self, features) -> None:
        def fill():
            self.feature.clear()
            for f in features:
                self.feature.addItem(f"Java {f}", f)
            if self.recommended:
                self.feature.setCurrentIndex(max(self.feature.findData(self.recommended), 0))
        self._safe(fill)

    def _choose(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self.selected = item.text(2)
            self.accept()

    def _download(self) -> None:
        feature = self.feature.currentData()
        if not feature:
            return
        self.dl_btn.setEnabled(False)

        def progress(text, value, maximum):
            self._safe(lambda: self.status.setText(f"{text} {value}%" if maximum else (text or "")))

        def done(j):
            self._safe(lambda: (self.dl_btn.setEnabled(True), self.status.setText(
                tr("✔ Java {v} installiert.").format(v=j.version))))
            self._load()

        run_task(lambda p: java.install_temurin(feature, p), done,
                 lambda err: self._safe(lambda: (self.dl_btn.setEnabled(True), self.status.setText(f"⚠ {err}"))),
                 lambda t, v, m: progress(t, v, m))


class InstanceSettingsDialog(QDialog):
    """Einstellungen nur für eine Instanz: Arbeitsspeicher, Java, Java-Argumente."""

    def __init__(self, instance, settings, parent=None, accounts=None):
        super().__init__(parent)
        self.instance = instance
        self.setWindowTitle(tr("Einstellungen – {name}").format(name=instance.name))
        self.setMinimumWidth(560)
        form = QFormLayout(self)

        self.own_ram = QCheckBox(tr("Eigenen Arbeitsspeicher für diese Instanz festlegen"))
        self.own_ram.setChecked(instance.ram_mb > 0)
        form.addRow(self.own_ram)
        self.ram = RamSlider(instance.ram_mb or settings.ram_mb)
        self.ram.setEnabled(self.own_ram.isChecked())
        self.own_ram.toggled.connect(self.ram.setEnabled)
        form.addRow(tr("Arbeitsspeicher"), self.ram)
        global_hint = QLabel(tr("Sonst gilt die allgemeine Einstellung ({gb} GB).").format(
            gb=f"{settings.ram_mb / 1024:.1f}"))
        global_hint.setObjectName("hint")
        form.addRow(global_hint)

        self.java = QLineEdit(instance.java_path)
        self.java.setPlaceholderText(settings.java_path or tr("leer = allgemeine Einstellung"))
        browse = QPushButton("…")
        browse.setFixedWidth(36)
        browse.clicked.connect(self._browse_java)
        javas = QPushButton(tr("☕ Verwalten …"))
        javas.clicked.connect(lambda: _pick_java(self, self.java, instance.mc_version))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.java, 1)
        row.addWidget(browse)
        row.addWidget(javas)
        wrap = QWidget()
        wrap.setLayout(row)
        form.addRow(tr("Java"), wrap)

        self.account = QComboBox()
        self.account.addItem(tr("Aktives Konto (Standard)"), "")
        for acc in accounts or []:
            self.account.addItem(acc.label, acc.id)
        self.account.setCurrentIndex(max(self.account.findData(instance.account_id), 0))
        form.addRow(tr("Konto"), self.account)
        acc_hint = QLabel(tr("Z.B. Survival immer mit dem Hauptkonto, Tests mit einem Zweitkonto."))
        acc_hint.setObjectName("hint")
        form.addRow(acc_hint)

        self.args = QLineEdit(instance.jvm_args)
        self.args.setPlaceholderText(tr("z.B. -XX:+UseG1GC (nur für Profis)"))
        form.addRow(tr("Java-Argumente"), self.args)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse_java(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("java.exe auswählen"), "",
                                              tr("Java (java.exe javaw.exe);;Alle Dateien (*)"))
        if path:
            self.java.setText(path)

    def _save(self):
        inst = self.instance
        inst.ram_mb = self.ram.value() if self.own_ram.isChecked() else 0
        inst.java_path = self.java.text().strip()
        inst.jvm_args = self.args.text().strip()
        inst.account_id = self.account.currentData() or ""
        inst.save()
        self.accept()


class AccentPicker(QWidget):
    """Farbtupfer zur Wahl der Akzentfarbe: Standard, Vorschläge oder eine eigene Farbe."""

    def __init__(self, value: str = "", parent=None):
        super().__init__(parent)
        from .style import ACCENTS
        self._value = value or ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.buttons = []
        for color, name in [("", "Standard")] + ACCENTS:
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedSize(26, 26)
            btn.setToolTip(tr(name))
            btn.setProperty("accent", color)
            btn.clicked.connect(lambda _=False, c=color: self._set(c))
            lay.addWidget(btn)
            self.buttons.append(btn)
        self.custom = QPushButton(tr("Eigene …"))
        self.custom.setObjectName("small")
        self.custom.clicked.connect(self._pick)
        lay.addWidget(self.custom)
        lay.addStretch(1)
        self._refresh()

    def value(self) -> str:
        return self._value

    def _set(self, color: str) -> None:
        self._value = color
        self._refresh()

    def _pick(self) -> None:
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(QColor(self._value or "#10b981"), self, tr("Akzentfarbe"))
        if color.isValid():
            self._set(color.name())

    def _refresh(self) -> None:
        from .style import PALETTES, current
        from .style import color as theme_color
        known = False
        for btn in self.buttons:
            c = btn.property("accent")
            on = c == self._value
            known |= on
            btn.setChecked(on)
            fill = c or PALETTES[current()]["accent"]
            label = "" if c else "A"
            btn.setText(label)
            btn.setStyleSheet(
                f"QPushButton {{ background: {fill}; border-radius: 13px; padding: 0; color: white; font-weight: 700;"
                f" border: {'3px solid ' + theme_color('strong') if on else '1px solid ' + theme_color('border2')}; }}")
        self.custom.setText(tr("Eigene …") if known else tr("Eigene: {c}").format(c=self._value))
