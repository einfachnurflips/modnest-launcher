"""Startbildschirm mit Logo und Ladebalken."""
from PySide6.QtCore import QElapsedTimer, QEasingCurve, QEventLoop, QPropertyAnimation, Qt, QThread
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QLabel, QProgressBar, QVBoxLayout, QWidget,
)

from ..config import APP_NAME, APP_VERSION
from .icons import logo_pixmap

SPLASH_STYLE = """
#card { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #151a22, stop:1 #0d1117);
        border: 1px solid #263040; border-radius: 22px; }
#name { color: #f1f5f9; font-size: 26pt; font-weight: 700; font-family: "Segoe UI Variable Display", "Segoe UI"; }
#tag { color: #7d8796; font-size: 10pt; }
#status { color: #94a3b8; font-size: 9pt; }
#version { color: #4b5563; font-size: 8pt; }
QProgressBar { background: #1e2530; border: none; border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34d399, stop:1 #10b981); }
"""


class Splash(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(SPLASH_STYLE)
        self.setFixedSize(460, 340)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        card = QFrame()
        card.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 160))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 34, 36, 26)
        lay.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(88))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(logo)
        lay.addSpacing(6)
        name = QLabel(APP_NAME)
        name.setObjectName("name")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(name)
        tag = QLabel("Minecraft-Launcher für Mods, Texturepacks & Shader")
        tag.setObjectName("tag")
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(tag)
        lay.addStretch(1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel("Starte …")
        self.status.setObjectName("status")
        lay.addWidget(self.status)
        ver = QLabel(f"v{APP_VERSION}")
        ver.setObjectName("version")
        ver.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(ver)

        self._anim = QPropertyAnimation(self.bar, b"value", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def step(self, text: str, percent: int, duration: int = 350) -> None:
        """Ladebalken animiert auf percent setzen und Statustext anzeigen."""
        self.status.setText(text)
        self._anim.stop()
        self._anim.setDuration(duration)
        self._anim.setStartValue(self.bar.value())
        self._anim.setEndValue(percent * 10)
        self._anim.start()
        # Animation sichtbar abspielen lassen, während der Start weiterläuft
        timer = QElapsedTimer()
        timer.start()
        while timer.elapsed() < duration:
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 16)
            QThread.msleep(8)

    def finish(self, window) -> None:
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(260)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.finished.connect(self.close)
        window.show()
        window.raise_()
        window.activateWindow()
        fade.start()
