"""Weitere Dialoge: Modpack exportieren, Absturz-Helfer, Patch-Notes, Welt-Backups."""
import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QTextBrowser, QVBoxLayout,
)

from .. import backup
from ..i18n import tr


class ExportDialog(QDialog):
    """Modpack exportieren: Format wählen (Modrinth oder CurseForge), Version, Speicherort."""

    def __init__(self, instance, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Modpack teilen"))
        self.setMinimumWidth(520)
        self.instance = instance
        self.target: Path | None = None
        lay = QVBoxLayout(self)
        title = QLabel(tr("„{name}“ als Modpack exportieren").format(name=instance.name))
        title.setObjectName("dialogtitle")
        lay.addWidget(title)
        hint = QLabel(tr("Die Datei kannst du Freunden schicken – sie lässt sich in fast jedem Launcher "
                         "importieren. Mods werden, wo möglich, als Download-Link gespeichert (kleine Datei), "
                         "alles andere wird direkt eingepackt."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.group = QButtonGroup(self)
        self.mr = QRadioButton(tr("Modrinth-Format (.mrpack) – für Modrinth App, Prism, ATLauncher, ModNest …"))
        self.cf = QRadioButton(tr("CurseForge-Format (.zip) – für CurseForge App, Prism, MultiMC, ModNest …"))
        self.mr.setChecked(True)
        for rb in (self.mr, self.cf):
            self.group.addButton(rb)
            lay.addWidget(rb)
        if not settings.curseforge_api_key.strip():
            note = QLabel(tr("Hinweis: Ohne CurseForge-API-Key werden beim CurseForge-Format alle Dateien "
                             "eingepackt (größere Datei, funktioniert aber trotzdem)."))
            note.setObjectName("warn")
            note.setWordWrap(True)
            lay.addWidget(note)

        form = QFormLayout()
        self.version = QLineEdit("1.0.0")
        form.addRow(tr("Version des Packs"), self.version)
        lay.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Speichern unter …"))
        buttons.accepted.connect(self._choose)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    @property
    def fmt(self) -> str:
        return "mrpack" if self.mr.isChecked() else "curseforge"

    def _choose(self):
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.instance.name).strip()
        ext, flt = (".mrpack", tr("Modrinth-Modpack (*.mrpack)")) if self.fmt == "mrpack" else \
            (".zip", tr("CurseForge-Modpack (*.zip)"))
        default = str(Path.home() / "Desktop" / f"{safe}-{self.version.text().strip() or '1.0.0'}{ext}")
        path, _ = QFileDialog.getSaveFileName(self, tr("Modpack speichern"), default, flt)
        if path:
            self.target = Path(path)
            self.accept()


class CrashDialog(QDialog):
    """Zeigt die wahrscheinliche Absturzursache verständlich an."""

    def __init__(self, info, instance, parent=None, disable_callback=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Minecraft ist abgestürzt"))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        title = QLabel("💥  " + tr(info.reason))
        title.setObjectName("dialogtitle")
        title.setWordWrap(True)
        lay.addWidget(title)
        if info.details:
            details = QTextBrowser()
            details.setPlainText(info.details)
            details.setMaximumHeight(160)
            lay.addWidget(details)
        if info.suspects:
            lay.addWidget(QLabel(tr("Verdächtige Mods:")))
            for mod_id in info.suspects:
                row = QHBoxLayout()
                row.addWidget(QLabel(f"•  {mod_id}"), 1)
                match = _find_mod(instance, mod_id)
                if match and disable_callback:
                    btn = QPushButton(tr("„{name}“ deaktivieren").format(name=match.name))
                    btn.setObjectName("small")
                    btn.clicked.connect(lambda _=False, m=match, b=btn: (disable_callback(m), b.setEnabled(False),
                                                                         b.setText(tr("deaktiviert"))))
                    row.addWidget(btn)
                lay.addLayout(row)
        for tip in info.tips:
            tip_label = QLabel("💡  " + tr(tip))
            tip_label.setWordWrap(True)
            tip_label.setObjectName("hint")
            lay.addWidget(tip_label)
        buttons = QHBoxLayout()
        if info.report:
            rep = QPushButton(tr("Crash-Report öffnen"))
            rep.clicked.connect(lambda: os.startfile(info.report))  # noqa: S606
            buttons.addWidget(rep)
        log = instance.path / "launcher-log.txt"
        if log.exists():
            log_btn = QPushButton(tr("Log öffnen"))
            log_btn.clicked.connect(lambda: os.startfile(log))  # noqa: S606
            buttons.addWidget(log_btn)
        buttons.addStretch(1)
        close = QPushButton(tr("Schließen"))
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        lay.addLayout(buttons)


def _find_mod(instance, mod_id: str):
    key = mod_id.lower().replace("-", "").replace("_", "")
    for m in instance.mods:
        if not m.enabled:
            continue
        name = m.name.lower().replace(" ", "").replace("-", "")
        file = m.file.lower().replace("-", "").replace("_", "")
        if key and (key in name or file.startswith(key)):
            return m
    return None


class PatchNotesDialog(QDialog):
    def __init__(self, title: str, html: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 680)
        lay = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setObjectName("dialogtitle")
        lay.addWidget(heading)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(html)
        lay.addWidget(browser, 1)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)


class WorldBackupsDialog(QDialog):
    """Welt-Backups einer Instanz anzeigen, sofort sichern und wiederherstellen."""

    def __init__(self, instance, settings, parent=None):
        super().__init__(parent)
        self.instance = instance
        self.settings = settings
        self.setWindowTitle(tr("Welt-Backups – {name}").format(name=instance.name))
        self.resize(640, 460)
        lay = QVBoxLayout(self)
        hint = QLabel(tr("Backups liegen in: {path}").format(path=backup.backup_root(settings) / "Welten"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        now = QPushButton(tr("💾  Alle Welten jetzt sichern"))
        now.clicked.connect(self.backup_now)
        row.addWidget(now)
        folder = QPushButton(tr("📁  Ordner öffnen"))
        folder.clicked.connect(self.open_folder)
        row.addWidget(folder)
        row.addStretch(1)
        restore = QPushButton(tr("Wiederherstellen"))
        restore.setObjectName("primary")
        restore.clicked.connect(self.restore)
        row.addWidget(restore)
        lay.addLayout(row)
        self.reload()

    def _instance_dir(self) -> Path:
        return backup.backup_root(self.settings) / "Welten" / backup._safe(self.instance.name)

    def reload(self):
        self.list.clear()
        root = self._instance_dir()
        files = sorted(root.rglob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []
        for f in files:
            size = f.stat().st_size / (1024 * 1024)
            item = QListWidgetItem(f"{f.parent.name}   ·   "
                                   f"{time.strftime('%d.%m.%Y %H:%M', time.localtime(f.stat().st_mtime))}   ·   {size:.1f} MB")
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            self.list.addItem(item)
        if not files:
            self.list.addItem(tr("Noch keine Backups vorhanden."))

    def backup_now(self):
        saves = self.instance.path / "saves"
        count = 0
        if saves.is_dir():
            for world in saves.iterdir():
                if (world / "level.dat").is_file():
                    backup.backup_world(world, self.instance.name, self.settings)
                    count += 1
        QMessageBox.information(self, tr("Backup"), tr("{n} Welt(en) gesichert.").format(n=count))
        self.reload()

    def open_folder(self):
        root = self._instance_dir()
        root.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(root)])

    def restore(self):
        items = self.list.selectedItems()
        if not items or not items[0].data(Qt.ItemDataRole.UserRole):
            return
        path = Path(items[0].data(Qt.ItemDataRole.UserRole))
        target = backup.restore_world(path, self.instance)
        QMessageBox.information(self, tr("Wiederhergestellt"),
                                tr("Die Welt wurde als „{name}“ wiederhergestellt. Deine aktuelle Welt bleibt "
                                   "unverändert.").format(name=target.name))
