"""Spielzeit-Statistik: Wochen-Diagramm und Spielzeit pro Instanz."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import playstats
from ..i18n import language, tr
from . import style
from .fmt import duration
from .icons import instance_icon


def _hours(seconds: int) -> str:
    if seconds <= 0:
        return "–"
    if seconds < 3600:
        return tr("{m} Min.").format(m=max(1, seconds // 60))
    value = f"{seconds / 3600:.1f}".rstrip("0").rstrip(".")
    return tr("{h} Std.").format(h=value if language() == "en" else value.replace(".", ","))


class WeekChart(QWidget):
    """Säulendiagramm: Spielzeit der letzten Wochen."""

    def __init__(self, data: list, parent=None):
        super().__init__(parent)
        self.data = data            # [(Montag, Sekunden)]
        self.setMinimumHeight(220)
        self.hover = -1
        self.setMouseTracking(True)

    def _bars(self):
        left, top, bottom = 8, 26, 34
        w = self.width() - left * 2
        h = self.height() - top - bottom
        n = max(len(self.data), 1)
        slot = w / n
        bar = min(slot * 0.62, 46)
        top_value = max([s for _, s in self.data] + [3600])
        out = []
        for i, (_, secs) in enumerate(self.data):
            bh = h * secs / top_value
            x = left + slot * i + (slot - bar) / 2
            out.append((QRectF(x, top + h - bh, bar, bh), QRectF(left + slot * i, top, slot, h + bottom)))
        return out, top + h

    def mouseMoveEvent(self, event) -> None:
        bars, _ = self._bars()
        hit = next((i for i, (_, area) in enumerate(bars) if area.contains(event.position())), -1)
        if hit != self.hover:
            self.hover = hit
            self.update()

    def leaveEvent(self, _event) -> None:
        self.hover = -1
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bars, base = self._bars()
        accent = QColor(style.color("accent"))
        faint = QColor(style.color("faint"))
        p.setPen(QColor(style.color("border2")))
        p.drawLine(8, int(base) + 1, self.width() - 8, int(base) + 1)
        small = QFont(self.font())
        small.setPointSizeF(8)
        p.setFont(small)
        last = len(bars) - 1
        for i, ((rect, area), (monday, secs)) in enumerate(zip(bars, self.data)):
            color = QColor(accent)
            if i != last and i != self.hover:
                color.setAlpha(150)
            if secs:
                path = QPainterPath()
                path.addRoundedRect(QRectF(rect.x(), rect.y(), rect.width(), max(rect.height(), 3)), 5, 5)
                p.fillPath(path, color)
            p.setPen(QColor(style.color("strong")) if i in (last, self.hover) else faint)
            label = tr("diese") if i == last else monday.strftime("%d.%m.")
            p.drawText(QRectF(area.x(), base + 6, area.width(), 18), Qt.AlignmentFlag.AlignHCenter, label)
            if secs and (i in (last, self.hover)):
                p.setPen(QColor(style.color("text")))
                p.drawText(QRectF(area.x() - 20, rect.y() - 20, area.width() + 40, 18),
                           Qt.AlignmentFlag.AlignHCenter, _hours(secs))
        p.end()


def _stat(value: str, label: str) -> QFrame:
    box = QFrame()
    box.setObjectName("card")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(2)
    v = QLabel(value)
    v.setObjectName("h2")
    font = v.font()
    font.setPointSize(16)
    v.setFont(font)
    lay.addWidget(v)
    lbl = QLabel(label)
    lbl.setObjectName("hint")
    lay.addWidget(lbl)
    return box


class StatsDialog(QDialog):
    def __init__(self, instances, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("📊 Spielzeit"))
        self.resize(760, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(14)
        title = QLabel(tr("📊 Spielzeit"))
        title.setObjectName("dialogtitle")
        lay.addWidget(title)

        logged = playstats.per_instance(36500)
        totals = {i.path.name: max(i.playtime, logged.get(i.path.name, 0)) for i in instances}
        total = sum(totals.values())
        streak = playstats.streak()
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_stat(_hours(playstats.this_week()), tr("diese Woche")))
        row.addWidget(_stat(_hours(playstats.since(30)), tr("letzte 30 Tage")))
        row.addWidget(_stat(_hours(total), tr("insgesamt")))
        row.addWidget(_stat(tr("{n} Tag(e)").format(n=streak) if streak else "–", tr("am Stück gespielt")))
        lay.addLayout(row)

        chart_box = QFrame()
        chart_box.setObjectName("card")
        cl = QVBoxLayout(chart_box)
        cl.setContentsMargins(14, 12, 14, 8)
        head = QLabel(tr("Letzte 12 Wochen"))
        head.setObjectName("cardtitle")
        cl.addWidget(head)
        cl.addWidget(WeekChart(playstats.weekly(12)))
        lay.addWidget(chart_box)

        if not playstats.sessions():
            hint = QLabel(tr("Die Wochen-Statistik sammelt ab jetzt jede Spielrunde. Die Gesamtzeit pro Instanz "
                             "stammt aus der bisherigen Zählung."))
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            lay.addWidget(hint)

        recent = playstats.per_instance(30)
        ordered = sorted(instances, key=lambda i: (recent.get(i.path.name, 0), totals[i.path.name]), reverse=True)
        ordered = [i for i in ordered if totals[i.path.name]]
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(4, 0, 4, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for col, text in enumerate(("", tr("Instanz"), tr("letzte 30 Tage"), tr("insgesamt"))):
            h = QLabel(text)
            h.setObjectName("section")
            grid.addWidget(h, 0, col)
        top = max([totals[i.path.name] for i in ordered] + [1])
        for r, inst in enumerate(ordered, start=1):
            icon = QLabel()
            icon.setPixmap(instance_icon(inst, 28).pixmap(28, 28))
            grid.addWidget(icon, r, 0)
            name_box = QVBoxLayout()
            name_box.setSpacing(3)
            name = QLabel(inst.name)
            name.setObjectName("cardtitle")
            name_box.addWidget(name)
            bar = QFrame()
            bar.setFixedHeight(5)
            bar.setFixedWidth(max(4, int(260 * totals[inst.path.name] / top)))
            bar.setStyleSheet(f"background: {style.color('accent')}; border-radius: 2px;")
            name_box.addWidget(bar)
            grid.addLayout(name_box, r, 1)
            grid.addWidget(QLabel(_hours(recent.get(inst.path.name, 0))), r, 2)
            grid.addWidget(QLabel(duration(totals[inst.path.name])), r, 3)
        if not ordered:
            empty = QLabel(tr("Noch nichts gespielt."))
            empty.setObjectName("empty")
            grid.addWidget(empty, 1, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(len(ordered) + 2, 1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        lay.addLayout(bottom)
