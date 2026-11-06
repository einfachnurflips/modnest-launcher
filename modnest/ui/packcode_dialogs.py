"""Pack-Code teilen und einlösen."""
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from .. import packcode
from ..i18n import tr
from ..instances import LOADERS
from ..sources import SourceError


def _title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("dialogtitle")
    return lbl


def _hint(text: str, name: str = "hint") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(name)
    lbl.setWordWrap(True)
    return lbl


class ShareCodeDialog(QDialog):
    def __init__(self, inst, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("🔗 Pack-Code – {name}").format(name=inst.name))
        self.setMinimumWidth(560)
        code, skipped = packcode.make(inst)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(10)
        lay.addWidget(_title(tr("🔗 Pack-Code für „{name}“").format(name=inst.name)))
        lay.addWidget(_hint(tr("Schick diesen Code deinen Freunden, z.B. in Discord. In ModNest unter 📥 → "
                               "„Pack-Code einlösen“ eingefügt, bekommen sie genau dieselben Mods in denselben Versionen.")))
        self.text = QPlainTextEdit(code)
        self.text.setReadOnly(True)
        self.text.setMaximumHeight(130)
        lay.addWidget(self.text)
        info = tr("{n} Zeichen").format(n=len(code))
        if len(code) > 1900:
            info += " · " + tr("Länger als eine Discord-Nachricht – Discord macht daraus automatisch eine Datei, "
                               "das ist okay.")
        lay.addWidget(_hint(info))
        if skipped:
            shown = ", ".join(skipped[:8]) + (" …" if len(skipped) > 8 else "")
            lay.addWidget(_hint(tr("⚠ Nicht dabei (eigene Dateien ohne Modrinth/CurseForge): {names}").format(names=shown),
                                "warn"))
        row = QHBoxLayout()
        row.addStretch(1)
        self.copy_btn = QPushButton(tr("📋 Kopieren"))
        self.copy_btn.setObjectName("primary")
        self.copy_btn.clicked.connect(lambda: self._copy(code))
        row.addWidget(self.copy_btn)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

    def _copy(self, code: str) -> None:
        QGuiApplication.clipboard().setText(code)
        self.copy_btn.setText(tr("✔ Kopiert"))
        QTimer.singleShot(1800, lambda: self.copy_btn.setText(tr("📋 Kopieren")))


class RedeemCodeDialog(QDialog):
    """Code einfügen → Vorschau → Name wählen → installieren (das Installieren macht das Hauptfenster)."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.data = None
        self.setWindowTitle(tr("🔗 Pack-Code einlösen"))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(10)
        lay.addWidget(_title(tr("🔗 Pack-Code einlösen")))
        lay.addWidget(_hint(tr("Füge den Code ein, den du bekommen hast (die ganze Nachricht geht auch).")))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("MODNEST1:…")
        self.text.setMaximumHeight(110)
        self.text.textChanged.connect(self._parse)
        lay.addWidget(self.text)
        self.preview = _hint("")
        lay.addWidget(self.preview)
        form = QFormLayout()
        self.name = QLineEdit()
        form.addRow(tr("Name der Instanz"), self.name)
        lay.addLayout(form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(tr("⬇ Installieren"))
        self.ok.setObjectName("primary")
        self.ok.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        clip = QGuiApplication.clipboard().text()
        if packcode.PREFIX in (clip or ""):
            self.text.setPlainText(clip)

    def _parse(self) -> None:
        raw = self.text.toPlainText()
        self.data = None
        self.ok.setEnabled(False)
        if not raw.strip():
            self.preview.setText("")
            return
        try:
            data = packcode.parse(raw)
        except SourceError as exc:
            self.preview.setObjectName("warn")
            self.preview.setText(f"⚠ {exc}")
            self._repolish()
            return
        s = packcode.summary(data)
        lines = [tr("<b>{name}</b> – Minecraft {mc}, {loader}").format(
            name=s["name"], mc=s["mc"], loader=LOADERS.get(s["loader"], s["loader"]))]
        if s["pack"]:
            lines.append(tr("📦 Modpack: {pack} {version}").format(pack=s["pack"], version=s["pack_version"]))
        parts = []
        for key, label in (("mods", tr("{n} Mod(s)")), ("resourcepacks", tr("{n} Texturepack(s)")),
                           ("shaderpacks", tr("{n} Shader"))):
            if s[key]:
                parts.append(label.format(n=s[key]))
        if parts:
            lines.append(("➕ " if s["pack"] else "") + ", ".join(parts) + (tr(" zusätzlich") if s["pack"] else ""))
        if s["needs_curseforge"] and not self.settings.curseforge_api_key.strip():
            lines.append(tr("⚠ Enthält Inhalte von CurseForge – dafür fehlt dir der CurseForge-API-Key."))
        self.preview.setObjectName("hint")
        self.preview.setText("<br>".join(lines))
        self._repolish()
        if not self.name.text().strip() or self.name.property("auto"):
            self.name.setText(s["name"])
            self.name.setProperty("auto", True)
        self.data = data
        self.ok.setEnabled(True)

    def _repolish(self) -> None:
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)
