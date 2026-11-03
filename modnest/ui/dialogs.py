"""Dialoge: neue Instanz, Instanz kopieren, Icon wählen, Einstellungen."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget,
)

from .. import backup, game
from ..i18n import LANGUAGES, tr
from ..instances import KINDS, LOADERS
from ..system import ram_rating, total_ram_mb
from .workers import run_task
from ..i18n import tr


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
        for key, label in (("dark", tr("🌙  Dunkel")), ("light", tr("☀  Hell")), ("system", tr("🖥  Wie Windows"))):
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(max(self.theme.findData(settings.theme), 0))
        form.addRow(tr("Design"), self.theme)
        self.language = QComboBox()
        for key, label in LANGUAGES.items():
            self.language.addItem(label, key)
        self.language.setCurrentIndex(max(self.language.findData(settings.language), 0))
        form.addRow(tr("Sprache / Language"), self.language)
        lang_hint = QLabel(tr("Die Sprache wird nach einem Neustart des Launchers übernommen."))
        lang_hint.setObjectName("hint")
        form.addRow(lang_hint)
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
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.java, 1)
        row.addWidget(browse)
        wrap = QWidget()
        wrap.setLayout(row)
        form.addRow(tr("Java"), wrap)
        self.tabs.addTab(game_tab, tr("🎮  Spiel"))

        # --- Konten & Dienste ----------------------------------------------
        acc_tab = QWidget()
        form = QFormLayout(acc_tab)
        self.cf_key = QLineEdit(settings.curseforge_api_key)
        self.cf_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cf_key.setPlaceholderText(tr("von console.curseforge.com"))
        form.addRow(tr("CurseForge API-Key"), self.cf_key)
        hint = QLabel(tr('Den kostenlosen Key bekommst du auf <a href="https://console.curseforge.com">'
                      "console.curseforge.com</a> → API Keys."))
        hint.setOpenExternalLinks(True)
        hint.setObjectName("hint")
        form.addRow(hint)
        self.ms_client = QLineEdit(settings.ms_client_id)
        self.ms_client.setPlaceholderText(tr("Anwendungs-ID (Client-ID) deiner Azure-App"))
        form.addRow(tr("Microsoft Client-ID"), self.ms_client)
        ms_hint = QLabel(tr("Für den Microsoft-Login brauchst du eine eigene, von Microsoft freigeschaltete "
                         "Azure-App – Anleitung in der README."))
        ms_hint.setWordWrap(True)
        ms_hint.setObjectName("hint")
        form.addRow(ms_hint)
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

    def _browse_backup(self):
        path = QFileDialog.getExistingDirectory(self, tr("Backup-Ordner wählen"), self.backup_dir.text())
        if path:
            self.backup_dir.setText(path)

    def _save(self):
        s = self.settings
        self.language_changed = s.language != self.language.currentData()
        s.theme = self.theme.currentData()
        s.language = self.language.currentData()
        s.backup_dir = self.backup_dir.text().strip()
        s.backup_worlds = self.bak_worlds.isChecked()
        s.backup_keep = self.bak_keep.value()
        s.backup_screenshots = self.bak_screens.isChecked()
        s.ram_mb = self.ram.value()
        s.java_path = self.java.text().strip()
        s.curseforge_api_key = self.cf_key.text().strip()
        s.ms_client_id = self.ms_client.text().strip()
        s.save()
        self.accept()
