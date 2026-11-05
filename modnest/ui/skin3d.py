"""Sich drehendes 3D-Modell eines Minecraft-Skins (mit Umhang) – ohne zusätzliche 3D-Bibliothek.

Jede Würfelfläche wird per Parallelprojektion gezeichnet: Bei paralleler Projektion wird ein
Rechteck exakt zu einem Parallelogramm, das lässt sich mit einer affinen QTransform abbilden.
Die Flächen werden von hinten nach vorne gezeichnet (Maler-Algorithmus).
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtWidgets import QWidget

# (u, v, Breite, Höhe, Tiefe) im Skin-Layout
FACES = ("top", "bottom", "right", "front", "left", "back")


def _uv(u, v, w, h, d) -> dict:
    return {
        "top": (u + d, v, w, d),
        "bottom": (u + d + w, v, w, d),
        "right": (u, v + d, d, h),
        "front": (u + d, v + d, w, h),
        "left": (u + d + w, v + d, d, h),
        "back": (u + 2 * d + w, v + d, w, h),
    }


def _corners(x0, y0, z0, x1, y1, z1) -> dict:
    """Je Fläche: Ecke oben-links, oben-rechts, unten-links der Textur (Blick von außen)."""
    return {
        "front": ((x0, y1, z1), (x1, y1, z1), (x0, y0, z1)),
        "back": ((x1, y1, z0), (x0, y1, z0), (x1, y0, z0)),
        "right": ((x0, y1, z0), (x0, y1, z1), (x0, y0, z0)),
        "left": ((x1, y1, z1), (x1, y1, z0), (x1, y0, z1)),
        "top": ((x0, y1, z0), (x1, y1, z0), (x0, y1, z1)),
        "bottom": ((x0, y0, z1), (x1, y0, z1), (x0, y0, z0)),
    }


def legacy_to_modern(img: QImage) -> QImage:
    """Alte 64×32-Skins: linker Arm/Bein = gespiegelter rechter Arm/Bein."""
    out = QImage(64, 64, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawImage(0, 0, img)
    for (su, sv), (du, dv) in (((0, 16), (16, 48)), ((40, 16), (32, 48))):
        src, dst = _uv(su, sv, 4, 12, 4), _uv(du, dv, 4, 12, 4)
        swap = {"right": "left", "left": "right"}
        for face in FACES:
            u, v, w, h = src[face]
            piece = img.copy(u, v, w, h).mirrored(True, False)
            du2, dv2, _, _ = dst[swap.get(face, face)]
            p.drawImage(du2, dv2, piece)
    p.end()
    return out


class SkinViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.skin: QImage | None = None
        self.cape: QImage | None = None
        self.slim = False
        self.yaw = 25.0
        self.pitch = 15.0
        self._drag = None
        self._auto = True
        self.setMinimumSize(220, 340)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("↔")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    # --- Daten -------------------------------------------------------------
    def set_skin(self, img: QImage | None, slim: bool = False) -> None:
        if img is not None and not img.isNull():
            img = img.convertToFormat(QImage.Format.Format_ARGB32)
            if img.height() == 32:
                img = legacy_to_modern(img)
        self.skin = img if img is not None and not img.isNull() else None
        self.slim = slim
        self.update()

    def set_cape(self, img: QImage | None) -> None:
        self.cape = img.convertToFormat(QImage.Format.Format_ARGB32) if img is not None and not img.isNull() else None
        self.update()

    # --- Bewegung ----------------------------------------------------------
    def _tick(self) -> None:
        if self._auto and self.isVisible():
            self.yaw = (self.yaw + 1.2) % 360
            self.update()

    def mousePressEvent(self, event) -> None:
        self._drag = (event.position(), self.yaw, self.pitch)
        self._auto = False
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag:
            start, yaw, pitch = self._drag
            delta = event.position() - start
            self.yaw = (yaw + delta.x() * 0.8) % 360
            self.pitch = max(-60.0, min(60.0, pitch + delta.y() * 0.5))
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        QTimer.singleShot(2500, lambda: setattr(self, "_auto", self._drag is None))

    def mouseDoubleClickEvent(self, event) -> None:
        self.yaw, self.pitch = 25.0, 15.0
        self.update()

    # --- Modell ------------------------------------------------------------
    def _boxes(self) -> list:
        """(Textur, Box-Min, Box-Max, UV-Herkunft, Größe, Aufblähung, Kippen)."""
        arm = 3 if self.slim else 4
        parts = [
            # Grundebene: (u, v), Box-Ursprung, Größe (b, h, t)
            ((0, 0), (-4, 24, -4), (8, 8, 8), 0.0),        # Kopf
            ((16, 16), (-4, 12, -2), (8, 12, 4), 0.0),     # Körper
            ((40, 16), (-4 - arm, 12, -2), (arm, 12, 4), 0.0),  # rechter Arm
            ((32, 48), (4, 12, -2), (arm, 12, 4), 0.0),    # linker Arm
            ((0, 16), (-4, 0, -2), (4, 12, 4), 0.0),       # rechtes Bein
            ((16, 48), (0, 0, -2), (4, 12, 4), 0.0),       # linkes Bein
            # zweite Ebene
            ((32, 0), (-4, 24, -4), (8, 8, 8), 0.5),
            ((16, 32), (-4, 12, -2), (8, 12, 4), 0.25),
            ((40, 32), (-4 - arm, 12, -2), (arm, 12, 4), 0.25),
            ((48, 48), (4, 12, -2), (arm, 12, 4), 0.25),
            ((0, 32), (-4, 0, -2), (4, 12, 4), 0.25),
            ((0, 48), (0, 0, -2), (4, 12, 4), 0.25),
        ]
        return parts

    def _project(self, point, scale, cx, cy, pivot=None, tilt=0.0):
        x, y, z = point
        if pivot is not None and tilt:
            # Umhang leicht nach hinten kippen (um die x-Achse am oberen Rand)
            py, pz = pivot
            ty, tz = y - py, z - pz
            ca, sa = math.cos(tilt), math.sin(tilt)
            y, z = py + ty * ca - tz * sa, pz + ty * sa + tz * ca
        y -= 16  # Modellmitte
        a, b = math.radians(self.yaw), math.radians(self.pitch)
        x, z = x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)
        y, z = y * math.cos(b) - z * math.sin(b), y * math.sin(b) + z * math.cos(b)
        return QPointF(cx + x * scale, cy - y * scale), z

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        scale = min(w / 26.0, h / 40.0)
        cx, cy = w / 2, h / 2 + scale
        # Schatten
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QPointF(cx, cy + 16 * scale * math.cos(math.radians(self.pitch))), 7 * scale, 2 * scale)
        if self.skin is None:
            p.end()
            return
        faces = []
        for (u, v), (x0, y0, z0), (bw, bh, bd), grow in self._boxes():
            uvs = _uv(u, v, bw, bh, bd)
            corners = _corners(x0 - grow, y0 - grow, z0 - grow, x0 + bw + grow, y0 + bh + grow, z0 + bd + grow)
            for face in FACES:
                faces.append((self.skin, uvs[face], corners[face], None, 0.0))
        if self.cape is not None:
            cw = self.cape.width() / 64.0
            cuv = _uv(0, 0, 10, 16, 1)
            cuv = {k: tuple(c * cw for c in val) for k, val in cuv.items()}
            corners = _corners(-5, 8, -3.2, 5, 24, -2.2)
            # Außenseite (sichtbar von hinten) = „front“-Bereich der Umhang-Textur
            mapping = {"back": "front", "front": "back", "left": "right", "right": "left", "top": "top", "bottom": "bottom"}
            for face in FACES:
                faces.append((self.cape, cuv[mapping[face]], corners[face], (24, -2.2), math.radians(10)))
        drawn = []
        for tex, (u, v, tw, th), (tl, tr, bl), pivot, tilt in faces:
            if tw <= 0 or th <= 0:
                continue
            p0, z0 = self._project(tl, scale, cx, cy, pivot, tilt)
            p1, z1 = self._project(tr, scale, cx, cy, pivot, tilt)
            p2, z2 = self._project(bl, scale, cx, cy, pivot, tilt)
            ex, ey = p1 - p0, p2 - p0
            # Rückseiten weglassen (Normale zeigt vom Betrachter weg)
            if ex.x() * ey.y() - ex.y() * ey.x() <= 0:
                continue
            br_z = z1 + z2 - z0
            drawn.append(((z0 + z1 + z2 + br_z) / 4, tex, (u, v, tw, th), p0, ex, ey))
        drawn.sort(key=lambda d: d[0])
        for _, tex, (u, v, tw, th), p0, ex, ey in drawn:
            t = QTransform(ex.x() / tw, ex.y() / tw, ey.x() / th, ey.y() / th, p0.x(), p0.y())
            p.setTransform(t)
            # minimal größer zeichnen, damit keine Haarrisse zwischen Flächen entstehen
            p.drawImage(QRectF(-0.03, -0.03, tw + 0.06, th + 0.06), tex, QRectF(u, v, tw, th))
        p.end()
