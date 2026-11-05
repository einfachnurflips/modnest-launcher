"""Projektseite: Beschreibung, Bilder und Links einer Mod / eines Packs direkt im Launcher."""
import re

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QImage, QPixmap, QTextDocument
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout,
)

from ..config import USER_AGENT
from ..i18n import tr
from .fmt import downloads_text
from .workers import run_task

LINK_LABELS = {"source": "💻 Quellcode", "issues": "🐞 Fehler melden", "wiki": "📖 Wiki", "discord": "💬 Discord",
               "website": "🌐 Webseite"}

# Deutsche Namen der Modrinth-Kategorien
CATEGORY_DE = {
    "adventure": "Abenteuer", "cursed": "Verflucht", "decoration": "Deko", "economy": "Wirtschaft",
    "equipment": "Ausrüstung", "food": "Essen", "game-mechanics": "Spielmechanik", "library": "Bibliothek",
    "magic": "Magie", "management": "Verwaltung", "minigame": "Minispiel", "mobs": "Mobs",
    "optimization": "Performance", "social": "Sozial", "storage": "Lager", "technology": "Technik",
    "transportation": "Transport", "utility": "Werkzeuge", "worldgen": "Weltgenerierung", "atmosphere": "Atmosphäre",
    "bloom": "Bloom", "cartoon": "Cartoon", "colored-lighting": "Farbiges Licht", "fantasy": "Fantasy",
    "foliage": "Pflanzen", "path-tracing": "Path-Tracing", "pbr": "PBR", "potato": "Für schwache PCs",
    "realistic": "Realistisch", "reflections": "Spiegelungen", "semi-realistic": "Halb-realistisch",
    "shadows": "Schatten", "screenshot": "Screenshots", "vanilla-like": "Wie Vanilla", "audio": "Sounds",
    "blocks": "Blöcke", "combat": "Kampf", "core-shaders": "Core-Shader", "entities": "Kreaturen",
    "environment": "Umgebung", "fonts": "Schriften", "gui": "Oberfläche", "items": "Items", "locale": "Sprachen",
    "models": "Modelle", "simplistic": "Schlicht", "themed": "Thematisch", "tweaks": "Anpassungen",
    "utility-pack": "Werkzeuge", "challenging": "Herausfordernd", "combat-pack": "Kampf", "kitchen-sink": "Alles drin",
    "lightweight": "Leichtgewicht", "multiplayer": "Mehrspieler", "quests": "Quests",
}


def category_label(name: str) -> str:
    from ..i18n import language
    if language() == "de" and name in CATEGORY_DE:
        return CATEGORY_DE[name]
    return name.replace("-", " ").capitalize()


class RemoteTextBrowser(QTextBrowser):
    """QTextBrowser, der Bilder aus dem Internet nachlädt (für Beschreibungen mit Bildern)."""

    MAX_WIDTH = 760

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self._net = QNetworkAccessManager(self)
        self._pending: set[str] = set()

    def loadResource(self, kind, url: QUrl):
        if kind == QTextDocument.ResourceType.ImageResource and url.scheme() in ("http", "https"):
            key = url.toString()
            if key not in self._pending:
                self._pending.add(key)
                req = QNetworkRequest(url)
                req.setRawHeader(b"User-Agent", USER_AGENT.encode())
                req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                                 QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
                reply = self._net.get(req)
                reply.finished.connect(lambda r=reply, u=QUrl(url): self._loaded(r, u))
            img = QImage(1, 1, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            return img
        return super().loadResource(kind, url)

    def _loaded(self, reply: QNetworkReply, url: QUrl) -> None:
        img = QImage()
        if reply.error() == QNetworkReply.NetworkError.NoError:
            img.loadFromData(reply.readAll())
        reply.deleteLater()
        if img.isNull():
            return
        width = min(self.MAX_WIDTH, max(200, self.viewport().width() - 40))
        if img.width() > width:
            img = img.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        try:
            doc = self.document()
            doc.addResource(QTextDocument.ResourceType.ImageResource, url, img)
            bar = self.verticalScrollBar().value()
            doc.markContentsDirty(0, doc.characterCount())
            self.verticalScrollBar().setValue(bar)
        except RuntimeError:
            pass


def _clean_markdown(text: str) -> str:
    # Bilder mit fester Breite/Höhe in HTML-Tags übernehmen Qt nicht immer – Größenangaben entfernen
    text = re.sub(r'\s(width|height)="?\d+%?"?', "", text)
    return text


class ProjectDialog(QDialog):
    """Generische Projektseite. load_details() liefert ein dict wie sources.modrinth.details()."""

    installLatest = Signal()
    chooseVersion = Signal()

    def __init__(self, title: str, author: str, summary: str, icon_url: str, url: str, load_details,
                 icon_loader=None, parent=None, installed: bool = False, can_choose: bool = True):
        super().__init__(parent)
        self.url = url
        self.icon_loader = icon_loader
        self.setWindowTitle(title)
        self.resize(980, 720)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(14)
        self.icon = QLabel()
        self.icon.setFixedSize(72, 72)
        head.addWidget(self.icon)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        name = QLabel(title + (tr("   ✔ installiert") if installed else ""))
        name.setObjectName("pagetitle")
        name.setWordWrap(True)
        titles.addWidget(name)
        self.meta = QLabel(author)
        self.meta.setObjectName("hint")
        titles.addWidget(self.meta)
        sub = QLabel(summary)
        sub.setWordWrap(True)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        lay.addLayout(head)

        self.tags = QLabel()
        self.tags.setObjectName("hint")
        self.tags.setWordWrap(True)
        lay.addWidget(self.tags)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.body = RemoteTextBrowser()
        self.body.setPlaceholderText(tr("Lade Beschreibung …"))
        self.tabs.addTab(self.body, tr("📄  Beschreibung"))
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.gallery.setIconSize(QSize(280, 158))
        self.gallery.setGridSize(QSize(300, 200))
        self.gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.gallery.setMovement(QListWidget.Movement.Static)
        self.gallery.setWordWrap(True)
        self.gallery.itemDoubleClicked.connect(self._open_image)
        self.tabs.addTab(self.gallery, tr("🖼  Bilder"))
        lay.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.links = QHBoxLayout()
        self.links.setSpacing(6)
        bottom.addLayout(self.links)
        bottom.addStretch(1)
        web = QPushButton(tr("🌐 Webseite"))
        web.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        web.setEnabled(bool(url))
        bottom.addWidget(web)
        if can_choose:
            choose = QPushButton(tr("⚙  Version wählen …"))
            choose.clicked.connect(lambda: (self.chooseVersion.emit(), self.accept()))
            bottom.addWidget(choose)
        install = QPushButton(tr("⬇  Neueste installieren"))
        install.setObjectName("primary")
        install.clicked.connect(lambda: (self.installLatest.emit(), self.accept()))
        bottom.addWidget(install)
        lay.addLayout(bottom)

        if icon_loader and icon_url:
            icon_loader.load(icon_url, self._set_icon)
        run_task(load_details, self._show, lambda err: self._safe(lambda: self.body.setPlainText(f"⚠ {err}")))

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except RuntimeError:
            pass

    def _set_icon(self, pix: QPixmap) -> None:
        self._safe(lambda: self.icon.setPixmap(pix.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation)))

    def _show(self, d: dict) -> None:
        self._safe(lambda: self._fill(d))

    def _fill(self, d: dict) -> None:
        parts = []
        if d.get("downloads"):
            parts.append(tr("⬇ {n} Downloads").format(n=downloads_text(d["downloads"])))
        if d.get("followers"):
            parts.append(f"♥ {downloads_text(d['followers'])}")
        if d.get("updated"):
            parts.append(tr("aktualisiert {date}").format(date=d["updated"][:10]))
        if d.get("license"):
            parts.append(f"⚖ {d['license']}")
        self.meta.setText("  ·  ".join([self.meta.text()] + parts if self.meta.text() else parts))
        tags = [category_label(c) for c in d.get("categories", []) if c]
        versions = d.get("versions") or []
        line = "  ".join(f"#{t}" for t in tags)
        if versions:
            line += ("     " if line else "") + tr("Minecraft: {v}").format(v=", ".join(versions))
        self.tags.setText(line)
        body = d.get("body") or ""
        if d.get("format") == "html":
            self.body.setHtml(body)
        elif d.get("format") == "text":
            self.body.setPlainText(body)
        else:
            self.body.setMarkdown(_clean_markdown(body))
        gallery = d.get("gallery") or []
        self.tabs.setTabText(1, tr("🖼  Bilder ({n})").format(n=len(gallery)))
        self.tabs.setTabEnabled(1, bool(gallery))
        for full, thumb, caption in gallery:
            item = QListWidgetItem(caption or "")
            item.setData(Qt.ItemDataRole.UserRole, full)
            item.setSizeHint(QSize(300, 200))
            self.gallery.addItem(item)
            if self.icon_loader and (thumb or full):
                self.icon_loader.load(thumb or full, lambda pix, it=item: self._safe(lambda: it.setIcon(QIcon(pix))))
        for key, link in (d.get("links") or {}).items():
            btn = QPushButton(tr(LINK_LABELS.get(key, key)))
            btn.setObjectName("small")
            btn.clicked.connect(lambda _=False, u=link: QDesktopServices.openUrl(QUrl(u)))
            self.links.addWidget(btn)

    def _open_image(self, item) -> None:
        url = item.data(Qt.ItemDataRole.UserRole)
        if url:
            ImageViewer(url, item.text(), self.icon_loader, self).exec()


class ImageViewer(QDialog):
    def __init__(self, url: str, caption: str, icon_loader, parent=None):
        super().__init__(parent)
        self.setWindowTitle(caption or tr("Bild"))
        self.resize(1200, 760)
        lay = QVBoxLayout(self)
        self.label = QLabel(tr("Lade Bild …"))
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.label, 1)
        self.pix = None
        if icon_loader:
            icon_loader.load(url, self._loaded)

    def _loaded(self, pix) -> None:
        self.pix = pix
        self._scale()

    def _scale(self) -> None:
        if self.pix is not None:
            try:
                self.label.setPixmap(self.pix.scaled(self.label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
            except RuntimeError:
                pass

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale()
