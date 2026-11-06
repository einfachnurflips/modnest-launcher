"""Komfort-Dialoge: Import aus anderen Launchern, Speicherplatz, Spiel-Konsole, Skins."""
import html
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QImage, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import bluemap, importers, skins, storage
from ..i18n import tr
from ..sources.base import session
from . import style
from .skin3d import SkinViewer
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


def render_cape(img: QImage, scale: int = 6) -> QPixmap:
    """Vorderseite eines Umhangs (10×16 Pixel der Textur)."""
    unit = max(img.width() // 64, 1)
    front = img.copy(1 * unit, 1 * unit, 10 * unit, 16 * unit)
    pix = QPixmap(10 * scale, 16 * scale)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    p.drawImage(QRect(0, 0, 10 * scale, 16 * scale), front)
    p.end()
    return pix


def _no_cape_icon(scale: int = 6) -> QPixmap:
    pix = QPixmap(10 * scale, 16 * scale)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = p.pen()
    pen.setColor(QColor(style.color("faint")))
    pen.setWidth(2)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawRoundedRect(QRect(3, 3, 10 * scale - 6, 16 * scale - 6), 6, 6)
    font = QFont()
    font.setPointSize(18)
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "∅")
    p.end()
    return pix


def _column(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(10)
    head = QLabel(title)
    head.setObjectName("h2")
    lay.addWidget(head)
    return frame, lay


class SkinDialog(QDialog):
    """Skin wechseln: links die 3D-Vorschau, in der Mitte die eigene Skin-Bibliothek, rechts die Umhänge.

    Der Skin, der gerade bei Minecraft eingestellt ist, wird automatisch in die Bibliothek übernommen –
    so geht er beim Wechseln nie verloren und bleibt immer auswählbar."""

    ACTIVE_MARK = "✔ "
    KEY = Qt.ItemDataRole.UserRole + 1

    def __init__(self, account, get_token, parent=None):
        super().__init__(parent)
        self.account = account
        self.get_token = get_token          # fn() → frischer Minecraft-Token (im Worker-Thread)
        self.profile = {}
        self.active_skin = None             # (QImage, slim) – so wie er gerade bei Minecraft eingestellt ist
        self.active_file = ""               # Bibliotheks-Datei, die dem aktiven Skin entspricht
        self.cape_images = {}               # Umhang-ID → QImage
        self._initial_cape = ""
        self.microsoft = account.kind == "microsoft"
        self.setWindowTitle(tr("👕 Skin – {name}").format(name=account.name))
        self.resize(1180, 640)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(14)
        cols = QHBoxLayout()
        cols.setSpacing(14)
        outer.addLayout(cols, 1)

        # --- Links: 3D-Vorschau ---------------------------------------------------
        left_frame, left = _column(tr("Vorschau"))
        self.viewer = SkinViewer()
        self.viewer.setFixedSize(260, 400)
        self.viewer.setToolTip(tr("Ziehen zum Drehen, Doppelklick setzt die Ansicht zurück"))
        left.addWidget(self.viewer, 0, Qt.AlignmentFlag.AlignHCenter)
        self.current = QLabel(tr("Lade aktuellen Skin …"))
        self.current.setObjectName("hint")
        self.current.setWordWrap(True)
        self.current.setMaximumWidth(260)
        left.addWidget(self.current)
        self.reset_btn = QPushButton(tr("↺ Aktuellen Skin zeigen"))
        self.reset_btn.setObjectName("small")
        self.reset_btn.clicked.connect(self._show_active)
        self.reset_btn.hide()
        left.addWidget(self.reset_btn)
        left.addStretch(1)
        cols.addWidget(left_frame)

        # --- Mitte: Meine Skins ---------------------------------------------------
        mid_frame, mid = _column(tr("Meine Skins"))
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(64, 128))
        self.list.setGridSize(QSize(118, 176))
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setWordWrap(True)
        self.list.currentItemChanged.connect(self._selected)
        self.list.itemDoubleClicked.connect(lambda _i: self._rename())
        mid.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton(tr("＋ Datei …"))
        add.setToolTip(tr("Skin-PNG von deinem PC hinzufügen"))
        add.clicked.connect(self._add)
        row.addWidget(add)
        player = QPushButton(tr("👤 Von Spieler …"))
        player.setToolTip(tr("Den Skin eines beliebigen Spielers über seinen Namen laden"))
        player.clicked.connect(self._from_player)
        row.addWidget(player)
        self.rename_btn = QPushButton(tr("✏ Umbenennen"))
        self.rename_btn.clicked.connect(self._rename)
        row.addWidget(self.rename_btn)
        self.remove_btn = QPushButton(tr("🗑 Entfernen"))
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        get = QPushButton(tr("🌐 Skins finden"))
        get.setToolTip("namemc.com")
        get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://namemc.com/minecraft-skins")))
        row.addWidget(get)
        mid.addLayout(row)
        cols.addWidget(mid_frame, 1)

        # --- Rechts: Umhänge ------------------------------------------------------
        right_frame, right = _column(tr("Umhänge"))
        right_frame.setFixedWidth(272)
        self.capes = QListWidget()
        self.capes.setViewMode(QListWidget.ViewMode.IconMode)
        self.capes.setIconSize(QSize(60, 96))
        self.capes.setGridSize(QSize(110, 140))
        self.capes.setMovement(QListWidget.Movement.Static)
        self.capes.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.capes.setWordWrap(True)
        self.capes.currentItemChanged.connect(self._cape_changed)
        right.addWidget(self.capes, 1)
        self.cape_hint = QLabel(tr("Lade Umhänge …") if self.microsoft
                                else tr("Umhänge gibt es nur mit einem Microsoft-Konto."))
        self.cape_hint.setObjectName("hint")
        self.cape_hint.setWordWrap(True)
        right.addWidget(self.cape_hint)
        cols.addWidget(right_frame)

        # --- Unten ----------------------------------------------------------------
        bottom = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        self.apply_btn = QPushButton(tr("✔ Anwenden"))
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._apply)
        bottom.addWidget(self.apply_btn)
        outer.addLayout(bottom)

        self._fill_library()
        if not self.microsoft:
            self.current.setText(tr("Offline-Konten haben keinen echten Skin. Skins kannst du nur mit einem "
                                    "Microsoft-Konto ändern – sammeln geht aber schon."))
            self.apply_btn.setEnabled(False)
            self.capes.setEnabled(False)
            if self.list.count():
                self.list.setCurrentRow(0)
        else:
            run_task(self._load_profile, lambda res: _safe(lambda: self._show_profile(res)),
                     lambda err: _safe(lambda: self.current.setText(f"⚠ {err}")))

    # --- Profil ---------------------------------------------------------------
    def _load_profile(self):
        prof = skins.profile(self.get_token())
        active = next((s for s in prof.get("skins", []) if s.get("state") == "ACTIVE"), None)
        data = session.get(active["url"], timeout=20).content if active else b""
        capes = {}
        for cape in prof.get("capes", []):
            if cape.get("url"):
                try:
                    capes[cape["id"]] = session.get(cape["url"], timeout=20).content
                except Exception:  # noqa: BLE001 – Umhang-Bild ist nur Vorschau
                    pass
        return prof, data, capes

    def _show_profile(self, result) -> None:
        prof, data, capes = result
        self.profile = prof
        self.cape_images = {cid: QImage.fromData(raw) for cid, raw in capes.items()}
        active = next((s for s in prof.get("skins", []) if s.get("state") == "ACTIVE"), {})
        img = QImage.fromData(data)
        if not img.isNull():
            variant = "slim" if active.get("variant", "CLASSIC").upper() == "SLIM" else "classic"
            self.active_skin = (img, variant == "slim")
            # Aktuellen Skin sichern, damit er beim Wechseln nicht verloren geht
            try:
                entry, added = skins.keep_skin(
                    data, tr("{name} – gesichert {date}").format(
                        name=self.account.name, date=datetime.now().strftime("%d.%m.%Y")), variant)
                self.active_file = entry["file"]
                if added:
                    self.status.setText(tr("✔ Dein aktueller Skin wurde in „Meine Skins“ gesichert – "
                                           "du kannst jederzeit zu ihm zurück."))
            except Exception:  # noqa: BLE001 – Sichern ist ein Extra, die Anzeige soll trotzdem gehen
                pass
        self._initial_cape = next((c["id"] for c in prof.get("capes", []) if c.get("state") == "ACTIVE"), "")
        self._fill_capes(prof.get("capes", []))
        self._fill_library()
        self._show_active()

    def _show_active(self) -> None:
        """Zeigt den Skin und Umhang, die gerade wirklich bei Minecraft eingestellt sind."""
        if self.active_skin:
            self.viewer.set_skin(*self.active_skin)
        self.viewer.set_cape(self.cape_images.get(self._initial_cape or ""))
        self._select(self.list, self.active_file)
        self._select(self.capes, self._initial_cape)
        self.current.setText(tr("Aktueller Skin von {name}").format(name=self.account.name))
        self.reset_btn.hide()

    def _select(self, widget: QListWidget, key: str) -> None:
        widget.blockSignals(True)
        widget.clearSelection()
        widget.setCurrentItem(None)
        for i in range(widget.count()):
            if widget.item(i).data(self.KEY) == key:
                widget.setCurrentRow(i)
                break
        widget.blockSignals(False)

    def _selected_skin(self) -> dict | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_cape(self) -> str:
        item = self.capes.currentItem()
        return item.data(self.KEY) if item else self._initial_cape

    def _update_preview_state(self) -> None:
        if not self.microsoft:
            return
        entry = self._selected_skin()
        skin_changed = entry is not None and entry["file"] != self.active_file
        if skin_changed or self._selected_cape() != self._initial_cape:
            self.current.setText(tr("👁 Vorschau – erst mit „Anwenden“ wird sie übernommen."))
            self.reset_btn.show()
        else:
            self.current.setText(tr("Aktueller Skin von {name}").format(name=self.account.name))
            self.reset_btn.hide()

    # --- Umhänge --------------------------------------------------------------
    def _fill_capes(self, capes: list) -> None:
        self.capes.blockSignals(True)
        self.capes.clear()
        none = QListWidgetItem(QIcon(_no_cape_icon()), tr("Kein Umhang"))
        none.setData(self.KEY, "")
        self.capes.addItem(none)
        for cape in capes:
            img = self.cape_images.get(cape["id"])
            icon = QIcon(render_cape(img)) if img is not None and not img.isNull() else QIcon(_no_cape_icon())
            name = cape.get("alias") or cape["id"]
            active = cape.get("state") == "ACTIVE"
            item = QListWidgetItem(icon, (self.ACTIVE_MARK if active else "") + name)
            item.setData(self.KEY, cape["id"])
            item.setToolTip(tr("Gerade eingestellt") if active else name)
            if active:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.capes.addItem(item)
        if not self._initial_cape:
            none.setText(self.ACTIVE_MARK + none.text())
        self.capes.blockSignals(False)
        self.cape_hint.setText(tr("{n} Umhang/Umhänge freigeschaltet.").format(n=len(capes)) if capes
                               else tr("Dieses Konto hat noch keine Umhänge."))

    def _cape_changed(self, item, _prev=None) -> None:
        if item is None:
            return
        self.viewer.set_cape(self.cape_images.get(item.data(self.KEY) or ""))
        self._update_preview_state()

    # --- Bibliothek -----------------------------------------------------------
    def _fill_library(self) -> None:
        keep = self._selected_skin()
        self.list.blockSignals(True)
        self.list.clear()
        for entry in skins.library():
            img = QImage(str(skins.library_dir() / entry["file"]))
            if img.isNull():
                continue
            pix = render_skin(img, entry.get("variant") == "slim", 4)
            active = entry["file"] == self.active_file
            item = QListWidgetItem(QIcon(pix), (self.ACTIVE_MARK if active else "") + entry["name"])
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setData(self.KEY, entry["file"])
            if active:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setToolTip(tr("Gerade bei Minecraft eingestellt"))
            self.list.addItem(item)
        self.list.blockSignals(False)
        if keep:
            self._select(self.list, keep["file"])
        has = self.list.count() > 0
        self.remove_btn.setEnabled(has)
        self.rename_btn.setEnabled(has)

    def _selected(self, item, _prev=None) -> None:
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        img = QImage(str(skins.library_dir() / entry["file"]))
        self.viewer.set_skin(img, entry.get("variant") == "slim")
        self._update_preview_state()

    def _show_entry(self, entry: dict) -> None:
        self._fill_library()
        self._select(self.list, entry["file"])
        self._selected(self.list.currentItem())

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
            entry = skins.add_to_library(Path(path), name.strip() or Path(path).stem,
                                         "slim" if variant.startswith(tr("Schmal")) else "classic")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Skin"), str(exc))
            return
        self._show_entry(entry)

    def _from_player(self) -> None:
        name, ok = QInputDialog.getText(self, tr("Skin von Spieler"), tr("Name des Spielers:"))
        name = name.strip()
        if not ok or not name:
            return
        self.status.setText(tr("Lade Skin von {name} …").format(name=name))

        def done(res):
            data, variant, real = res
            try:
                entry, added = skins.keep_skin(data, real, variant)
            except Exception as exc:  # noqa: BLE001
                self.status.setText(f"⚠ {exc}")
                return
            self._show_entry(entry)
            self.status.setText(tr("✔ Skin von {name} hinzugefügt.").format(name=real) if added
                                else tr("Diesen Skin hast du schon: „{name}“.").format(name=entry["name"]))

        run_task(lambda: skins.player_skin(name), lambda res: _safe(lambda: done(res)),
                 lambda err: _safe(lambda: self.status.setText(f"⚠ {err}")))

    def _rename(self) -> None:
        entry = self._selected_skin()
        if not entry:
            return
        name, ok = QInputDialog.getText(self, tr("Skin umbenennen"), tr("Name:"), text=entry["name"])
        if ok and name.strip():
            skins.rename_in_library(entry, name.strip())
            self._fill_library()

    def _remove(self) -> None:
        entry = self._selected_skin()
        if not entry:
            return
        text = tr("„{name}“ aus der Bibliothek entfernen?").format(name=entry["name"])
        if entry["file"] == self.active_file:
            text += "\n\n" + tr("Das ist dein aktueller Skin. Bei Minecraft bleibt er eingestellt, "
                                "beim nächsten Öffnen wird er wieder gesichert.")
        if QMessageBox.question(self, tr("Skin"), text) == QMessageBox.StandardButton.Yes:
            skins.remove_from_library(entry)
            self._fill_library()

    def _apply(self) -> None:
        entry = self._selected_skin()
        if entry is not None and entry["file"] == self.active_file:
            entry = None
        cape = self._selected_cape()
        cape_changed = self.capes.isEnabled() and self.capes.count() > 0 and cape != self._initial_cape
        if entry is None and not cape_changed:
            self.status.setText(tr("Das ist schon so eingestellt – wähle einen anderen Skin oder Umhang."))
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
            if entry is not None:
                self.active_skin = (QImage(str(skins.library_dir() / entry["file"])), entry.get("variant") == "slim")
                self.active_file = entry["file"]
            if cape_changed:
                self._initial_cape = cape
                for c in self.profile.get("capes", []):
                    c["state"] = "ACTIVE" if c["id"] == cape else "INACTIVE"
                self._fill_capes(self.profile.get("capes", []))
            self._fill_library()
            self.apply_btn.setEnabled(True)
            self._show_active()
            self.status.setText(tr("✔ Gespeichert! Im Spiel siehst du den neuen Skin nach dem nächsten Start."))

        run_task(work, lambda r: _safe(lambda: done(r)),
                 lambda err: _safe(lambda: (self.apply_btn.setEnabled(True), self.status.setText(f"⚠ {err}"))))


# --- BlueMap-Karte -----------------------------------------------------------------
class MapDialog(QDialog):
    """Adresse der BlueMap eines Servers eingeben/prüfen und die Karte öffnen."""

    def __init__(self, settings, address: str, name: str, parent=None):
        super().__init__(parent)
        self.settings, self.address = settings, address
        self.setWindowTitle(tr("🗺 Karte – {name}").format(name=name))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        title = QLabel(tr("BlueMap von {name}").format(name=name))
        title.setObjectName("dialogtitle")
        lay.addWidget(title)
        hint = QLabel(tr("Läuft auf dem Server die Mod/das Plugin BlueMap, kannst du dir die 3D-Karte hier ansehen. "
                         "Meist ist sie unter Port 8100 erreichbar – sonst frag den Server-Betreiber nach der Adresse."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        row = QHBoxLayout()
        self.url = QLineEdit(bluemap.saved_url(settings, address) or bluemap.guess_url(address))
        self.url.returnPressed.connect(self._open)
        row.addWidget(self.url, 1)
        test = QPushButton(tr("Prüfen"))
        test.clicked.connect(self._check)
        row.addWidget(test)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QHBoxLayout()
        browser = QPushButton(tr("Im Browser öffnen"))
        browser.clicked.connect(lambda: self._open(browser=True))
        buttons.addWidget(browser)
        buttons.addStretch(1)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.open_btn = QPushButton(tr("🗺  Karte öffnen"))
        self.open_btn.setObjectName("primary")
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(lambda: self._open())
        buttons.addWidget(self.open_btn)
        lay.addLayout(buttons)
        self._check()

    def _check(self) -> None:
        url = bluemap.normalize(self.url.text())
        self.status.setText(tr("Prüfe {url} …").format(url=url))

        def done(maps):
            text = tr("✔ BlueMap gefunden") + (f" – {', '.join(maps)}" if maps else "")
            _safe(lambda: self.status.setText(text))

        run_task(lambda: bluemap.check(url), done,
                 lambda err: _safe(lambda: self.status.setText(
                     tr("⚠ Unter dieser Adresse wurde keine BlueMap gefunden. Prüfe die Adresse oder frag den "
                        "Server-Betreiber."))))

    def _open(self, browser: bool = False) -> None:
        url = bluemap.normalize(self.url.text())
        if not url:
            return
        bluemap.save_url(self.settings, self.address, url)
        if browser or not bluemap.open_window(url):
            QDesktopServices.openUrl(QUrl(url))
        self.accept()
