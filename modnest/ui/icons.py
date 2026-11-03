"""Selbst gezeichnete Icons (App-Logo, Instanz-Avatare) – keine externen Bilddateien nötig."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap, QPolygonF

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
    font = QFont("Segoe UI")
    font.setPixelSize(max(int(size * 0.4), 8))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("white"))
    letters = "".join(w[0] for w in name.split()[:2]).upper() or "?"
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letters)
    p.end()
    return QIcon(pix)


def _rounded(pix: QPixmap, size: int) -> QPixmap:
    """Schneidet ein Bild quadratisch zu, skaliert es und rundet die Ecken ab."""
    side = min(pix.width(), pix.height())
    square = pix.copy((pix.width() - side) // 2, (pix.height() - side) // 2, side, side)
    square = square.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.28, size * 0.28)
    p.setClipPath(path)
    p.drawPixmap(0, 0, square)
    p.end()
    return out


def instance_icon(inst, size: int = 40) -> QIcon:
    """Eigenes Icon der Instanz, sonst der farbige Buchstaben-Avatar."""
    path = inst.icon_path
    icon = None
    if path:
        pix = QPixmap(str(path))
        if not pix.isNull():
            icon = QIcon(_rounded(pix, size))
    icon = icon or instance_avatar(inst.name, inst.loader, size)
    # Ausgewählte Listeneinträge sollen das Icon nicht abdunkeln
    icon.addPixmap(icon.pixmap(size, size), QIcon.Mode.Selected)
    return icon


def save_instance_icon(inst, image: QImage | QPixmap) -> bool:
    """Speichert ein Bild quadratisch zugeschnitten (256 px) als icon.png in den Instanz-Ordner."""
    pix = QPixmap.fromImage(image) if isinstance(image, QImage) else image
    if pix.isNull():
        return False
    side = min(pix.width(), pix.height())
    square = pix.copy((pix.width() - side) // 2, (pix.height() - side) // 2, side, side)
    # Pixel-Art (z.B. 64x64 Mod-Icons) scharf vergrößern, Fotos weich skalieren
    mode = Qt.TransformationMode.FastTransformation if side <= 128 else Qt.TransformationMode.SmoothTransformation
    square = square.scaled(256, 256, Qt.AspectRatioMode.IgnoreAspectRatio, mode)
    if not square.save(str(inst.path / "icon.png"), "PNG"):
        return False
    inst.icon = "icon.png"
    inst.save()
    return True


def reset_instance_icon(inst) -> None:
    if inst.icon_path:
        inst.icon_path.unlink(missing_ok=True)
    inst.icon = ""
    inst.save()


def save_ico(path) -> None:
    """Speichert das Logo als .ico (für die Desktop-Verknüpfung)."""
    logo_pixmap(256).save(str(path), "ICO")
