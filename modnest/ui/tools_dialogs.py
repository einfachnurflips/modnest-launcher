"""Werkzeug-Dialoge: Kompatibilitäts-Check, Performance-Paket, Changelog."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTextBrowser,
    QVBoxLayout, QWidget,
)

from .. import compat, perf
from ..i18n import tr
from .workers import run_task


def _card(parent_layout) -> QVBoxLayout:
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(4)
    parent_layout.addWidget(frame)
    return lay


class CompatDialog(QDialog):
    """Zeigt das Ergebnis des Kompatibilitäts-Checks mit Ein-Klick-Lösungen."""

    searchRequested = Signal(str)     # Mod-ID, die in „Entdecken“ gesucht werden soll

    def __init__(self, instance, parent=None):
        super().__init__(parent)
        self.instance = instance
        self.changed = False
        self.setWindowTitle(tr("Kompatibilitäts-Check – {name}").format(name=instance.name))
        self.resize(720, 520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        self.summary = QLabel(tr("Prüfe Mods …"))
        self.summary.setObjectName("dialogtitle")
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.list = QVBoxLayout(body)
        self.list.setSpacing(10)
        self.list.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        row = QHBoxLayout()
        again = QPushButton(tr("Erneut prüfen"))
        again.clicked.connect(self.run)
        row.addWidget(again)
        row.addStretch(1)
        close = QPushButton(tr("Schließen"))
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        outer.addLayout(row)
        self.run()

    def run(self) -> None:
        self.summary.setText(tr("Prüfe Mods …"))
        inst = self.instance
        run_task(lambda: compat.check(inst), self._show,
                 lambda err: self._safe(lambda: self.summary.setText(f"⚠ {err}")))

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except RuntimeError:
            pass

    def _show(self, issues) -> None:
        self._safe(lambda: self._fill(issues))

    def _fill(self, issues) -> None:
        while self.list.count() > 1:
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        errors = sum(1 for i in issues if i.severity == "error")
        if not issues:
            self.summary.setText(tr("✔ Keine Probleme gefunden – die Mods sollten zusammen laufen."))
            return
        self.summary.setText(tr("{e} Problem(e) und {w} Hinweis(e) gefunden").format(e=errors, w=len(issues) - errors))
        for issue in issues:
            box = QFrame()
            box.setObjectName("card")
            lay = QVBoxLayout(box)
            lay.setContentsMargins(14, 10, 14, 10)
            icon = "⛔" if issue.severity == "error" else "⚠"
            title = QLabel(f"{icon}  {issue.title}")
            title.setObjectName("cardtitle")
            title.setWordWrap(True)
            lay.addWidget(title)
            detail = QLabel(issue.detail)
            detail.setObjectName("hint")
            detail.setWordWrap(True)
            lay.addWidget(detail)
            files = QLabel("  ·  ".join(issue.files))
            files.setObjectName("hint")
            files.setWordWrap(True)
            lay.addWidget(files)
            actions = QHBoxLayout()
            actions.addStretch(1)
            for text, fn in self._fixes(issue):
                btn = QPushButton(text)
                btn.setObjectName("small")
                btn.clicked.connect(fn)
                actions.addWidget(btn)
            lay.addLayout(actions)
            self.list.insertWidget(self.list.count() - 1, box)

    def _fixes(self, issue) -> list:
        fixes = []
        if issue.kind == "missing":
            for dep in issue.deps[:3]:
                fixes.append((tr("🔍 {dep} suchen").format(dep=dep), lambda _=False, d=dep: self._search(d)))
        elif len(issue.files) == 1:
            fixes.append((tr("Deaktivieren"), lambda _=False, f=issue.files: self._disable(f)))
        elif len(issue.files) > 1:
            cs = self.instance.content["mods"]
            files = sorted(issue.files, key=lambda f: (cs.folder / f).stat().st_mtime if (cs.folder / f).exists() else 0)
            if issue.kind == "duplicate":
                fixes.append((tr("Ältere deaktivieren"), lambda _=False, f=files[:-1]: self._disable(f)))
            else:
                for f in issue.files:
                    fixes.append((tr("{file} deaktivieren").format(file=f[:28]), lambda _=False, x=[f]: self._disable(x)))
        return fixes

    def _disable(self, files: list) -> None:
        cs = self.instance.content["mods"]
        for f in files:
            cs.set_enabled(f, False)
        self.instance.save()
        self.changed = True
        self.run()

    def _search(self, dep: str) -> None:
        self.searchRequested.emit(dep)
        self.accept()


class PerfDialog(QDialog):
    """Performance-Paket: zeigt passende Performance-Mods zum Ankreuzen."""

    def __init__(self, instance, parent=None):
        super().__init__(parent)
        self.instance = instance
        self.options = []
        self.checks = []
        self.setWindowTitle(tr("⚡ Performance-Paket"))
        self.resize(620, 500)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        title = QLabel(tr("Mehr FPS mit einem Klick"))
        title.setObjectName("dialogtitle")
        outer.addWidget(title)
        sub = QLabel(tr("Diese bewährten Mods machen Minecraft schneller, ohne das Spielgefühl zu verändern. "
                        "Passend zu Minecraft {mc} mit {loader}.").format(mc=instance.mc_version, loader=instance.loader))
        sub.setObjectName("hint")
        sub.setWordWrap(True)
        outer.addWidget(sub)
        self.list = QVBoxLayout()
        self.list.setSpacing(6)
        outer.addLayout(self.list)
        self.status = QLabel(tr("Prüfe, welche Mods für deine Version verfügbar sind …"))
        self.status.setObjectName("hint")
        outer.addWidget(self.status)
        outer.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(tr("⬇  Installieren"))
        self.ok.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        run_task(lambda: perf.options(instance), self._loaded,
                 lambda err: self._safe(lambda: self.status.setText(f"⚠ {err}")))

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except RuntimeError:
            pass

    def _loaded(self, options) -> None:
        self.options = options
        self._safe(self._fill)

    def _fill(self) -> None:
        for opt in self.options:
            row = QHBoxLayout()
            box = QCheckBox(f"{opt.mod.name}")
            box.setChecked(opt.status == "ok")
            box.setEnabled(opt.status == "ok")
            box.toggled.connect(self._update)
            row.addWidget(box)
            what = QLabel(opt.mod.what if opt.status == "ok" else f"{opt.mod.what}  ({opt.note})")
            what.setObjectName("hint")
            what.setWordWrap(True)
            row.addWidget(what, 1)
            self.list.addLayout(row)
            self.checks.append((box, opt))
        available = sum(1 for o in self.options if o.status == "ok")
        self.status.setText(tr("{n} Mod(s) können installiert werden. Sie landen in der Kategorie „Performance“.").format(n=available)
                            if available else tr("✔ Alles Wichtige ist schon installiert oder nicht verfügbar."))
        self._update()

    def _update(self) -> None:
        n = len(self.selected())
        self.ok.setEnabled(n > 0)
        self.ok.setText(tr("⬇  {n} installieren").format(n=n))

    def selected(self) -> list:
        return [opt for box, opt in self.checks if box.isChecked() and opt.status == "ok"]


class ChangelogDialog(QDialog):
    def __init__(self, title: str, text: str, parent=None, markdown: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        if not text.strip():
            view.setPlainText(tr("Kein Changelog verfügbar."))
        elif markdown:
            view.setMarkdown(text)
        else:
            view.setHtml(text)
        lay.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
