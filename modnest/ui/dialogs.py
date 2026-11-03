"""Dialoge: neue Instanz, Einstellungen."""
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QWidget,
)

from .. import game
from ..instances import LOADERS
from .workers import run_task


class NewInstanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Neue Instanz")
        self.setMinimumWidth(420)
        form = QFormLayout(self)

        self.name = QLineEdit("Mein Modpack")
        form.addRow("Name", self.name)

        self.version = QComboBox()
        self.version.setEditable(True)
        self.version.addItem("Lade Versionen …")
        self.snapshots = QCheckBox("Snapshots anzeigen")
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
        form.addRow("Mod-Loader", self.loader)

        hint = QLabel("Tipp: Fabric hat die meisten Performance-Mods (Sodium, Lithium …).")
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
                 lambda err: self.version.setItemText(0, "Offline? Version manuell eingeben"))

    def _fill_versions(self, versions):
        try:
            self.version.clear()
            self.version.addItems(versions)
        except RuntimeError:
            pass  # Dialog schon geschlossen

    def values(self) -> tuple[str, str, str]:
        return self.name.text().strip(), self.version.currentText().strip(), self.loader.currentData()


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(520)
        form = QFormLayout(self)

        self.ram = QSpinBox()
        self.ram.setRange(1024, 65536)
        self.ram.setSingleStep(512)
        self.ram.setSuffix(" MB")
        self.ram.setValue(settings.ram_mb)
        form.addRow("Arbeitsspeicher", self.ram)

        self.java = QLineEdit(settings.java_path)
        self.java.setPlaceholderText("leer = automatisch (Mojang-Java wird heruntergeladen)")
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse_java)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.java, 1)
        row.addWidget(browse)
        wrap = QWidget()
        wrap.setLayout(row)
        form.addRow("Java", wrap)

        self.cf_key = QLineEdit(settings.curseforge_api_key)
        self.cf_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cf_key.setPlaceholderText("von console.curseforge.com")
        form.addRow("CurseForge API-Key", self.cf_key)
        hint = QLabel('Den kostenlosen Key bekommst du auf <a href="https://console.curseforge.com">'
                      "console.curseforge.com</a> → API Keys.")
        hint.setOpenExternalLinks(True)
        hint.setObjectName("hint")
        form.addRow(hint)

        self.ms_client = QLineEdit(settings.ms_client_id)
        self.ms_client.setPlaceholderText("Anwendungs-ID (Client-ID) deiner Azure-App")
        form.addRow("Microsoft Client-ID", self.ms_client)
        ms_hint = QLabel('Für den Microsoft-Login brauchst du eine eigene, von Mojang freigeschaltete Azure-App – '
                         'Anleitung in der README.')
        ms_hint.setWordWrap(True)
        ms_hint.setObjectName("hint")
        form.addRow(ms_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse_java(self):
        path, _ = QFileDialog.getOpenFileName(self, "java.exe auswählen", "", "Java (java.exe javaw.exe);;Alle Dateien (*)")
        if path:
            self.java.setText(path)

    def _save(self):
        s = self.settings
        s.ram_mb = self.ram.value()
        s.java_path = self.java.text().strip()
        s.curseforge_api_key = self.cf_key.text().strip()
        s.ms_client_id = self.ms_client.text().strip()
        s.save()
        self.accept()
