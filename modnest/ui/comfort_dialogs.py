"""Komfort-Dialoge: Import aus anderen Launchern, Speicherplatz, Spiel-Konsole, Skins."""
import html
import re
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication, QIcon, QImage, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import importers, skins, storage
from ..i18n import tr
from ..sources.base import session
from .workers import run_task


def _safe(fn) -> None:
    try:
        fn()
    except RuntimeError:
        pass   # Fenster wurde inzwischen geschlossen


# --- Import aus anderen Launchern ----------------------------------------------------
class ImportLaunchersDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.found = []
        self.setWindowTitle(tr("Aus anderen Launchern übernehmen"))
        self.resize(720, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        title = QLabel(tr("Instanzen aus anderen Launchern übernehmen"))
        title.setObjectName("dialogtitle")
        lay.addWidget(title)
        hint = QLabel(tr("ModNest kopiert Mods, Configs, Texturepacks, Shader und auf Wunsch die Welten. "
                         "Die Originale im anderen Launcher bleiben unverändert."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(28, 28))
        self.tree.itemChanged.connect(self._update)
        lay.addWidget(self.tree, 1)
        self.worlds = QCheckBox(tr("Welten mitkopieren"))
        self.worlds.setChecked(True)
        lay.addWidget(self.worlds)
        self.status = QLabel(tr("Suche nach anderen Launchern …"))
        self.status.setObjectName("hint")
        lay.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        run_task(importers.find_all, lambda res: _safe(lambda: self._fill(res)),
                 lambda err: _safe(lambda: self.status.setText(f"⚠ {err}")))

    def _fill(self, found) -> None:
        self.found = found
        groups = {}
        self.tree.blockSignals(True)
        for i, f in enumerate(found):
            if f.launcher not in groups:
                head = QTreeWidgetItem([f.launcher])
                font = head.font(0)
                font.setBold(True)
                head.setFont(0, font)
                head.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.tree.addTopLevelItem(head)
                head.setExpanded(True)
                groups[f.launcher] = head
            item = QTreeWidgetItem([f.label if not f.official else
                                    tr("Welten, Texturepacks und Einstellungen aus dem offiziellen Launcher")])
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            if f.icon:
                item.setIcon(0, QIcon(str(f.icon)))
            groups[f.launcher].addChild(item)
        self.tree.blockSignals(False)
        self.status.setText(tr("{n} Instanz(en) in {l} Launcher(n) gefunden.").format(n=len(found), l=len(groups))
                            if found else tr("Keine anderen Launcher gefunden."))
        self._update()

    def selected(self) -> list:
        result = []
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                child = head.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    result.append(self.found[child.data(0, Qt.ItemDataRole.UserRole)])
        return result

    def _update(self, *_) -> None:
        n = len(self.selected())
        self.ok.setEnabled(n > 0)
        self.ok.setText(tr("{n} übernehmen").format(n=n))


# --- Speicherplatz -------------------------------------------------------------------
class StorageDialog(QDialog):
    def __init__(self, instances, settings, parent=None):
        super().__init__(parent)
        self.instances, self.settings = instances, settings
        self.report = None
        self.freed = 0
        self.setWindowTitle(tr("Speicherplatz"))
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        self.title = QLabel(tr("Berechne Speicherplatz …"))
        self.title.setObjectName("dialogtitle")
        lay.addWidget(self.title)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Was"), tr("Größe"), tr("davon Welten")])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tree, 1)
        clean_title = QLabel(tr("🧹  Aufräumen"))
        clean_title.setObjectName("h2")
        lay.addWidget(clean_title)
        self.clean_box = QVBoxLayout()
        lay.addLayout(self.clean_box)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(tr("Schließen"))
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.title.setText(tr("Berechne Speicherplatz …"))
        run_task(lambda: storage.analyze(self.instances, self.settings),
                 lambda rep: _safe(lambda: self._show(rep)),
                 lambda err: _safe(lambda: self.title.setText(f"⚠ {err}")))

    def _show(self, rep) -> None:
        self.report = rep
        self.tree.clear()
        self.title.setText(tr("ModNest belegt insgesamt {size}").format(size=storage.human(rep.total)))
        for inst, total, worlds in sorted(rep.instances, key=lambda r: -r[1]):
            self.tree.addTopLevelItem(QTreeWidgetItem([f"📦  {inst.name}", storage.human(total),
                                                       storage.human(worlds) if worlds else "–"]))
        for label, size in rep.shared:
            self.tree.addTopLevelItem(QTreeWidgetItem([f"🗂  {label}", storage.human(size), ""]))
        for col in (1, 2):
            self.tree.resizeColumnToContents(col)
        while self.clean_box.count():
            w = self.clean_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not rep.cleanups:
            done = QLabel(tr("✔ Nichts aufzuräumen.") + (tr("  {size} freigegeben.").format(
                size=storage.human(self.freed)) if self.freed else ""))
            done.setObjectName("hint")
            self.clean_box.addWidget(done)
        for c in rep.cleanups:
            line = QWidget()
            hl = QHBoxLayout(line)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(QLabel(f"{c.label}  ·  {storage.human(c.size)}"), 1)
            btn = QPushButton(tr("Löschen"))
            btn.setObjectName("small")
            btn.clicked.connect(lambda _=False, c=c: self._clean(c))
            hl.addWidget(btn)
            self.clean_box.addWidget(line)

    def _clean(self, cleanup) -> None:
        if QMessageBox.question(self, tr("Aufräumen"), tr("„{what}“ endgültig löschen ({size})?\n\n"
                                                         "Minecraft lädt benötigte Dateien beim nächsten Start "
                                                         "automatisch wieder herunter.").format(
                what=cleanup.label, size=storage.human(cleanup.size))) != QMessageBox.StandardButton.Yes:
            return
        self.freed += storage.clean(cleanup)
        self.refresh()


# --- Spiel-Konsole -----------------------------------------------------------------
LEVEL_COLORS = (
    (re.compile(r"\b(ERROR|FATAL|SEVERE)\b|Exception|Caused by:|^\s+at ", re.I), "#f87171"),
    (re.compile(r"\bWARN(ING)?\b"), "#fbbf24"),
)


class LogWindow(QDialog):
    """Zeigt die Ausgabe von Minecraft live an (liest launcher-log.txt mit)."""

    def __init__(self, instance, parent=None):
        super().__init__(parent)
        self.instance = instance
        self.path = Path(instance.path) / "launcher-log.txt"
        self.pos = 0
        self.lines: list[str] = []
        self.setWindowTitle(tr("📜 Konsole – {name}").format(name=instance.name))
        self.resize(1000, 620)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("🔍  Filtern …"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._rerender)
        bar.addWidget(self.filter, 1)
        self.only_errors = QCheckBox(tr("Nur Fehler & Warnungen").replace("&", "&&"))
        self.only_errors.toggled.connect(self._rerender)
        bar.addWidget(self.only_errors)
        self.follow = QCheckBox(tr("Mitscrollen"))
        self.follow.setChecked(True)
        bar.addWidget(self.follow)
        copy = QPushButton(tr("Kopieren"))
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText("\n".join(self.lines)))
        bar.addWidget(copy)
        self.share = QPushButton(tr("🔗 Log teilen"))
        self.share.setToolTip(tr("Lädt das Log auf mclo.gs hoch und kopiert den Link – praktisch, um Hilfe zu bekommen."))
        self.share.clicked.connect(self._share)
        bar.addWidget(self.share)
        lay.addLayout(bar)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(20000)
        self.view.setFont(QFont("Consolas", 9))
        lay.addWidget(self.view, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(500)
        self._poll()

    def _poll(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.pos:      # neues Spiel gestartet → Datei neu
            self.pos, self.lines = 0, []
            self.view.clear()
        if size == self.pos:
            return
        with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(self.pos)
            chunk = fh.read()
            self.pos = fh.tell()
        new = chunk.splitlines()
        self.lines += new
        for line in new:
            self._append(line)

    def _matches(self, line: str) -> bool:
        text = self.filter.text().strip().lower()
        if text and text not in line.lower():
            return False
        if self.only_errors.isChecked():
            return any(rx.search(line) for rx, _ in LEVEL_COLORS)
        return True

    def _append(self, line: str) -> None:
        if not self._matches(line):
            return
        color = next((c for rx, c in LEVEL_COLORS if rx.search(line)), None)
        escaped = html.escape(line).replace("	", "    ").replace("  ", "&nbsp; ")
        self.view.appendHtml(f'<span style="color:{color}">{escaped}</span>' if color else escaped)
        if self.follow.isChecked():
            self.view.moveCursor(QTextCursor.MoveOperation.End)

    def _rerender(self) -> None:
        self.view.clear()
        for line in self.lines[-20000:]:
            self._append(line)

    def _share(self) -> None:
        if QMessageBox.question(self, tr("Log teilen"), tr(
                "Das Log wird öffentlich auf mclo.gs hochgeladen (Zugangsdaten und IP-Adressen entfernt mclo.gs "
                "automatisch). Fortfahren?")) != QMessageBox.StandardButton.Yes:
            return
        text = "\n".join(self.lines)[-9_000_000:]
        self.share.setEnabled(False)

        def work():
            resp = session.post("https://api.mclo.gs/1/log", data={"content": text}, timeout=30)
            data = resp.json()
            if not data.get("success"):
                raise OSError(data.get("error", "Upload fehlgeschlagen"))
            return data["url"]

        def done(url):
            _safe(lambda: self.share.setEnabled(True))
            QGuiApplication.clipboard().setText(url)
            QMessageBox.information(self, tr("Log teilen"), tr("Link kopiert:\n{url}").format(url=url))
            QDesktopServices.openUrl(QUrl(url))

        run_task(work, done, lambda err: (_safe(lambda: self.share.setEnabled(True)),
                                          QMessageBox.warning(self, tr("Log teilen"), err)))


# --- Skins -------------------------------------------------------------------------
def render_skin(img: QImage, slim: bool, scale: int = 8) -> QPixmap:
    """Zeichnet die Vorderansicht eines Skins (inkl. zweiter Ebene)."""
    legacy = img.height() == 32
    arm = 3 if slim else 4
    w, h = 16, 32
    pix = QPixmap(w * scale, h * scale)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

    def part(sx, sy, sw, sh, dx, dy, mirror=False):
        piece = img.copy(sx, sy, sw, sh)
        if mirror:
            piece = piece.mirrored(True, False)
        p.drawImage(QRect(dx * scale, dy * scale, sw * scale, sh * scale), piece)

    # Grundebene
    part(8, 8, 8, 8, 4, 0)                    # Kopf
    part(20, 20, 8, 12, 4, 8)                 # Körper
    part(44, 20, arm, 12, 4 - arm, 8)         # rechter Arm (vom Betrachter links)
    part(4, 20, 4, 12, 4, 20)                 # rechtes Bein
    if legacy:
        part(44, 20, arm, 12, 12, 8, True)
        part(4, 20, 4, 12, 8, 20, True)
    else:
        part(36, 52, arm, 12, 12, 8)          # linker Arm
        part(20, 52, 4, 12, 8, 20)            # linkes Bein
        # zweite Ebene
        part(20, 36, 8, 12, 4, 8)
        part(44, 36, arm, 12, 4 - arm, 8)
        part(52, 52, arm, 12, 12, 8)
        part(4, 36, 4, 12, 4, 20)
        part(4, 52, 4, 12, 8, 20)
    part(40, 8, 8, 8, 4, 0)                   # Hut
    p.end()
    return pix


class SkinDialog(QDialog):
    """Skin wechseln: Bibliothek eigener Skins, Hochladen zu Minecraft, Umhang wählen."""

    def __init__(self, account, get_token, parent=None):
        super().__init__(parent)
        self.account = account
        self.get_token = get_token          # fn() → frischer Minecraft-Token (im Worker-Thread)
        self.profile = {}
        self.setWindowTitle(tr("👕 Skin – {name}").format(name=account.name))
        self.resize(820, 560)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(18)

        left = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(16 * 12 + 20, 32 * 12 + 20)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setObjectName("card")
        left.addWidget(self.preview)
        self.current = QLabel(tr("Lade aktuellen Skin …"))
        self.current.setObjectName("hint")
        self.current.setWordWrap(True)
        self.current.setMaximumWidth(16 * 12 + 20)
        left.addWidget(self.current)
        left.addStretch(1)
        lay.addLayout(left)

        right = QVBoxLayout()
        head = QLabel(tr("Meine Skins"))
        head.setObjectName("dialogtitle")
        right.addWidget(head)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(64, 128))
        self.list.setGridSize(QSize(110, 170))
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.currentItemChanged.connect(self._selected)
        right.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton(tr("＋ Skin hinzufügen …"))
        add.clicked.connect(self._add)
        row.addWidget(add)
        self.remove_btn = QPushButton(tr("Entfernen"))
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        get = QPushButton(tr("Skins finden"))
        get.setToolTip("namemc.com")
        get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://namemc.com/minecraft-skins")))
        row.addWidget(get)
        right.addLayout(row)
        cape_row = QHBoxLayout()
        cape_row.addWidget(QLabel(tr("Umhang:")))
        self.capes = QComboBox()
        self.capes.addItem(tr("Kein Umhang"), "")
        self.capes.setEnabled(False)
        cape_row.addWidget(self.capes, 1)
        right.addLayout(cape_row)
        self.status = QLabel()
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        self.apply_btn = QPushButton(tr("✔ Anwenden"))
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._apply)
        bottom.addWidget(self.apply_btn)
        right.addLayout(bottom)
        lay.addLayout(right, 1)

        self._fill_library()
        if account.kind != "microsoft":
            self.current.setText(tr("Offline-Konten haben keinen echten Skin. Skins kannst du nur mit einem "
                                    "Microsoft-Konto ändern – sammeln geht aber schon."))
            self.apply_btn.setEnabled(False)
        else:
            run_task(self._load_profile, lambda res: _safe(lambda: self._show_profile(res)),
                     lambda err: _safe(lambda: self.current.setText(f"⚠ {err}")))

    # --- Profil ---------------------------------------------------------------
    def _load_profile(self):
        prof = skins.profile(self.get_token())
        active = next((s for s in prof.get("skins", []) if s.get("state") == "ACTIVE"), None)
        data = session.get(active["url"], timeout=20).content if active else b""
        return prof, data

    def _show_profile(self, result) -> None:
        prof, data = result
        self.profile = prof
        img = QImage.fromData(data)
        active = next((s for s in prof.get("skins", []) if s.get("state") == "ACTIVE"), {})
        if not img.isNull():
            self._preview(img, active.get("variant", "CLASSIC").upper() == "SLIM")
        self.current.setText(tr("Aktueller Skin von {name}").format(name=self.account.name))
        self.capes.clear()
        self.capes.addItem(tr("Kein Umhang"), "")
        for cape in prof.get("capes", []):
            self.capes.addItem(cape.get("alias", cape["id"]), cape["id"])
            if cape.get("state") == "ACTIVE":
                self.capes.setCurrentIndex(self.capes.count() - 1)
        self.capes.setEnabled(self.capes.count() > 1)
        self._initial_cape = self.capes.currentData()

    def _preview(self, img: QImage, slim: bool) -> None:
        self.preview.setPixmap(render_skin(img, slim, 12))

    # --- Bibliothek -----------------------------------------------------------
    def _fill_library(self) -> None:
        self.list.clear()
        for entry in skins.library():
            img = QImage(str(skins.library_dir() / entry["file"]))
            if img.isNull():
                continue
            pix = render_skin(img, entry.get("variant") == "slim", 4)
            item = QListWidgetItem(QIcon(pix), entry["name"])
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)
        self.remove_btn.setEnabled(self.list.count() > 0)

    def _selected(self, item, _prev=None) -> None:
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        img = QImage(str(skins.library_dir() / entry["file"]))
        self._preview(img, entry.get("variant") == "slim")

    def _add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Skin auswählen"), str(Path.home() / "Downloads"),
                                              tr("Skin (*.png)"))
        if not path:
            return
        name, ok = QInputDialog.getText(self, tr("Skin hinzufügen"), tr("Name:"), text=Path(path).stem)
        if not ok:
            return
        variant, ok = QInputDialog.getItem(self, tr("Skin hinzufügen"), tr("Armbreite:"),
                                           [tr("Klassisch (4 Pixel)"), tr("Schmal (3 Pixel, „Alex“)")], 0, False)
        if not ok:
            return
        try:
            skins.add_to_library(Path(path), name.strip() or Path(path).stem,
                                 "slim" if variant.startswith(tr("Schmal")) else "classic")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Skin"), str(exc))
            return
        self._fill_library()
        self.list.setCurrentRow(self.list.count() - 1)

    def _remove(self) -> None:
        item = self.list.currentItem()
        if item and QMessageBox.question(self, tr("Skin"), tr("„{name}“ aus der Bibliothek entfernen?").format(
                name=item.text())) == QMessageBox.StandardButton.Yes:
            skins.remove_from_library(item.data(Qt.ItemDataRole.UserRole))
            self._fill_library()

    def _apply(self) -> None:
        item = self.list.currentItem()
        entry = item.data(Qt.ItemDataRole.UserRole) if item else None
        cape = self.capes.currentData() if self.capes.isEnabled() else None
        cape_changed = self.capes.isEnabled() and cape != getattr(self, "_initial_cape", None)
        if entry is None and not cape_changed:
            self.status.setText(tr("Wähle zuerst einen Skin aus deiner Bibliothek."))
            return
        self.apply_btn.setEnabled(False)
        self.status.setText(tr("Übertrage zu Minecraft …"))

        def work():
            token = self.get_token()
            if entry is not None:
                skins.upload(token, skins.library_dir() / entry["file"], entry.get("variant", "classic"))
            if cape_changed:
                skins.set_cape(token, cape or None)
            return True

        def done(_):
            _safe(lambda: (self.apply_btn.setEnabled(True), self.status.setText(
                tr("✔ Gespeichert! Im Spiel siehst du den neuen Skin nach dem nächsten Start."))))
            self._initial_cape = cape

        run_task(work, done, lambda err: _safe(lambda: (self.apply_btn.setEnabled(True), self.status.setText(f"⚠ {err}"))))
