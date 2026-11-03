"""Selbst gezeichnete Icons (App-Logo, Instanz-Avatare) – keine externen Bilddateien nötig."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap, QPolygonF

LOADER_COLORS = {
    "fabric": ("#dbb68f", "#a3835d"),
    "quilt": ("#c084fc", "#7c3aed"),
    "forge": ("#60a5fa", "#1d4ed8"),
    "neoforge": ("#fb923c", "#c2410c"),
    "vanilla": ("#4ade80", "#15803d"),
}


def logo_pixmap(size: int = 256) -> QPixmap:
    """Abgerundetes Quadrat mit grünem Verlauf und einem isometrischen Block."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size
    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0, QColor("#34d399"))
    grad.setColorAt(1, QColor("#059669"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92), s * 0.22, s * 0.22)
    p.fillPath(path, grad)

    cx, cy, r = s * 0.5, s * 0.52, s * 0.27
    top = QPolygonF([QPointF(cx, cy - r), QPointF(cx + r * 0.95, cy - r * 0.48),
                     QPointF(cx, cy + r * 0.04), QPointF(cx - r * 0.95, cy - r * 0.48)])
    left = QPolygonF([QPointF(cx - r * 0.95, cy - r * 0.48), QPointF(cx, cy + r * 0.04),
                      QPointF(cx, cy + r * 1.08), QPointF(cx - r * 0.95, cy + r * 0.56)])
    right = QPolygonF([QPointF(cx + r * 0.95, cy - r * 0.48), QPointF(cx, cy + r * 0.04),
                       QPointF(cx, cy + r * 1.08), QPointF(cx + r * 0.95, cy + r * 0.56)])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 245))
    p.drawPolygon(top)
    p.setBrush(QColor(255, 255, 255, 170))
    p.drawPolygon(left)
    p.setBrush(QColor(255, 255, 255, 115))
    p.drawPolygon(right)
    p.end()
    return pix


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(size))
    return icon


def instance_avatar(name: str, loader: str, size: int = 40) -> QIcon:
    light, dark = LOADER_COLORS.get(loader, ("#94a3b8", "#475569"))
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor(light))
    grad.setColorAt(1, QColor(dark))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.28, size * 0.28)
    p.fillPath(path, grad)
    font = QFont("Segoe UI", int(size * 0.38))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("white"))
    letters = "".join(w[0] for w in name.split()[:2]).upper() or "?"
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letters)
    p.end()
    return QIcon(pix)


def save_ico(path) -> None:
    """Speichert das Logo als .ico (für die Desktop-Verknüpfung)."""
    logo_pixmap(256).save(str(path), "ICO")
