"""Screenshots aller Instanzen als Galerie mit Großansicht und automatischem Backup."""
import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from .. import backup
from .workers import run_task
from ..i18n import tr

THUMB = QSize(240, 135)


def _load_thumbs(paths: list[Path]) -> list[tuple[Path, QImage]]:
    """Lädt verkleinerte Vorschaubilder (läuft im Hintergrund, QImage ist dafür thread-sicher)."""
    result = []
    for p in paths:
        img = QImage(str(p))
        if not img.isNull():
            result.append((p, img.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         Qt.TransformationMode.SmoothTransformation)))
    return result


class ImageViewer(QDialog):
    """Großansicht mit Vor/Zurück (Pfeiltasten)."""

    def __init__(self, paths: list[Path], index: int, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.index = index
        self.resize(1200, 760)
        lay = QVBoxLayout(self)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(400, 300)
        lay.addWidget(self.image, 1)
        bar = QHBoxLayout()
        prev_btn = QPushButton("◀")
        prev_btn.clicked.connect(lambda: self.step(-1))
        next_btn = QPushButton("▶")
        next_btn.clicked.connect(lambda: self.step(1))
        self.caption = QLabel()
        self.caption.setObjectName("hint")
        copy_btn = QPushButton(tr("📋  Kopieren"))
        copy_btn.clicked.connect(self.copy)
        show_btn = QPushButton(tr("📁  Im Ordner zeigen"))
        show_btn.clicked.connect(lambda: _reveal(self.paths[self.index]))
        bar.addWidget(prev_btn)
        bar.addWidget(next_btn)
        bar.addWidget(self.caption, 1)
        bar.addWidget(copy_btn)
        bar.addWidget(show_btn)
        lay.addLayout(bar)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self.step(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self.step(1))
        self._pix = QPixmap()
        self.show_current()

    def show_current(self):
        path = self.paths[self.index]
        self._pix = QPixmap(str(path))
        self.setWindowTitle(path.name)
        self.caption.setText(f"{self.index + 1} / {len(self.paths)}  ·  {path.parent.parent.name}  ·  "
                             + time.strftime("%d.%m.%Y %H:%M", time.localtime(path.stat().st_mtime)))
        self._fit()

    def _fit(self):
        if not self._pix.isNull():
            self.image.setPixmap(self._pix.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def step(self, delta: int):
        self.index = (self.index + delta) % len(self.paths)
        self.show_current()

    def copy(self):
        QGuiApplication.clipboard().setPixmap(self._pix)


def _reveal(path: Path) -> None:
    subprocess.Popen(["explorer", "/select,", str(path)])


class ScreenshotsPage(QWidget):
    message = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.instances = []
        self.paths: list[Path] = []
        self._req = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 14)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(self._label(tr("🖼  Screenshots"), "pagetitle"), 1)
        self.filter = QComboBox()
        self.filter.setMinimumWidth(200)
        self.filter.currentIndexChanged.connect(lambda _: self.reload())
        head.addWidget(self.filter)
        backup_btn = QPushButton(tr("💾  Jetzt sichern"))
        backup_btn.clicked.connect(self.backup_now)
        head.addWidget(backup_btn)
        folder_btn = QPushButton(tr("📁  Backup-Ordner"))
        folder_btn.clicked.connect(self.open_backup)
        head.addWidget(folder_btn)
        lay.addLayout(head)
        self.info = self._label("", "hint")
        lay.addWidget(self.info)

        self.gallery = QListWidget()
        self.gallery.setObjectName("gallery")
        self.gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.gallery.setIconSize(THUMB)
        self.gallery.setGridSize(QSize(THUMB.width() + 22, THUMB.height() + 46))
        self.gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.gallery.setMovement(QListWidget.Movement.Static)
        self.gallery.setUniformItemSizes(True)
        self.gallery.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.gallery.itemDoubleClicked.connect(self._open)
        self.gallery.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.gallery.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.gallery, 1)
        self.empty = self._label(tr("Noch keine Screenshots. Drücke im Spiel F2, um einen zu machen."), "empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)

    @staticmethod
    def _label(text, name):
        lbl = QLabel(text)
        lbl.setObjectName(name)
        return lbl

    def set_instances(self, instances) -> None:
        self.instances = instances
        current = self.filter.currentData()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem(tr("Alle Instanzen"), "")
        for inst in instances:
            self.filter.addItem(inst.name, str(inst.path))
        idx = self.filter.findData(current)
        self.filter.setCurrentIndex(max(idx, 0))
        self.filter.blockSignals(False)

    def reload(self) -> None:
        selected = self.filter.currentData()
        paths = []
        for inst in self.instances:
            if selected and str(inst.path) != selected:
                continue
            folder = inst.path / "screenshots"
            if folder.is_dir():
                paths += [p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        self.paths = paths
        self.gallery.clear()
        self.empty.setVisible(not paths)
        self.info.setText(tr("{n} Screenshot(s) · Doppelklick für Großansicht · Rechtsklick für mehr").format(n=len(paths))
                          if paths else "")
        names = {str(i.path): i.name for i in self.instances}
        for p in paths:
            item = QListWidgetItem(time.strftime("%d.%m.%Y  %H:%M", time.localtime(p.stat().st_mtime)))
            item.setToolTip(f"{names.get(str(p.parent.parent), '')}\n{p.name}")
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            item.setSizeHint(QSize(THUMB.width() + 16, THUMB.height() + 40))
            self.gallery.addItem(item)
        self._req += 1
        req = self._req
        # Vorschaubilder in Häppchen laden, damit die Galerie sofort erscheint
        for start in range(0, len(paths), 24):
            chunk = paths[start:start + 24]
            run_task(lambda c=chunk: _load_thumbs(c), lambda res, r=req: self._thumbs(r, res))

    def _thumbs(self, req, results) -> None:
        if req != self._req:
            return
        index = {self.gallery.item(i).data(Qt.ItemDataRole.UserRole): self.gallery.item(i)
                 for i in range(self.gallery.count())}
        for path, img in results:
            item = index.get(str(path))
            if item is not None:
                pix = QPixmap.fromImage(img)
                x = max((pix.width() - THUMB.width()) // 2, 0)
                y = max((pix.height() - THUMB.height()) // 2, 0)
                item.setIcon(QIcon(pix.copy(x, y, THUMB.width(), THUMB.height())))

    def _selected_paths(self) -> list[Path]:
        return [Path(i.data(Qt.ItemDataRole.UserRole)) for i in self.gallery.selectedItems()]

    def _open(self, item) -> None:
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        ImageViewer(self.paths, self.paths.index(path), self).exec()

    def _menu(self, pos) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        menu = QMenu(self)
        menu.addAction(tr("🔍  Großansicht"), lambda: ImageViewer(self.paths, self.paths.index(paths[0]), self).exec())
        menu.addAction(tr("📋  Kopieren"), lambda: QGuiApplication.clipboard().setPixmap(QPixmap(str(paths[0]))))
        menu.addAction(tr("📁  Im Ordner zeigen"), lambda: _reveal(paths[0]))
        menu.addSeparator()
        menu.addAction(tr("🗑  Löschen …"), lambda: self._delete(paths))
        menu.exec(self.gallery.viewport().mapToGlobal(pos))

    def _delete(self, paths: list[Path]) -> None:
        text = tr("{n} Screenshot(s) aus der Instanz löschen? Bereits gesicherte Kopien im Backup-Ordner bleiben erhalten.")
        if QMessageBox.question(self, tr("Löschen"), text.format(n=len(paths))) == QMessageBox.StandardButton.Yes:
            for p in paths:
                p.unlink(missing_ok=True)
            self.reload()

    def backup_now(self) -> None:
        total = 0
        for inst in self.instances:
            total += backup.backup_screenshots(inst, self.settings)
        self.message.emit(tr("✔ {n} neue Screenshot(s) gesichert nach {path}").format(
            n=total, path=backup.backup_root(self.settings) / "Screenshots"))

    def open_backup(self) -> None:
        folder = backup.backup_root(self.settings) / "Screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # noqa: S606
