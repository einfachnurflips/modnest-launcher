"""Home: Weiterspielen, zuletzt gespielte Welten und Server (mit Status), Mod-Updates, Minecraft-News."""
from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import news, updates, worlds
from ..instances import LOADERS
from .fmt import ago, duration
from .icons import instance_icon, logo_pixmap
from .workers import run_task
from ..i18n import tr


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear(item.layout())


def _label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


class ClickableFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class HomePage(QWidget):
    playRequested = Signal(object)                 # Instance
    openInstance = Signal(object)                  # Instance
    joinWorld = Signal(object, str)                # Instance, Ordner
    joinServer = Signal(object, str)               # Instance, Adresse
    updateRequested = Signal(object, list)         # Instance, [Update]
    patchNotesRequested = Signal(object)           # NewsItem
    newInstanceRequested = Signal()
    importRequested = Signal()

    def __init__(self, settings, icon_loader, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.icon_loader = icon_loader
        self.instances = []
        self.focus = None
        self._news = None
        self._updates: dict[str, list] = {}
        self._launcher_update = None
        self._req = 0
        self.display_name = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        self.layout_ = QVBoxLayout(body)
        self.layout_.setContentsMargins(28, 22, 28, 22)
        self.layout_.setSpacing(16)

        self.greeting = _label("", "pagetitle")
        self.layout_.addWidget(self.greeting)
        self.banner = QFrame()
        self.banner.setObjectName("card")
        self.banner_layout = QHBoxLayout(self.banner)
        self.banner.hide()
        self.layout_.addWidget(self.banner)

        self.hero = QFrame()
        self.hero.setObjectName("card")
        self.hero_layout = QHBoxLayout(self.hero)
        self.hero_layout.setContentsMargins(20, 18, 20, 18)
        self.hero_layout.setSpacing(16)
        self.layout_.addWidget(self.hero)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        self.worlds_box, self.worlds_list = self._section(tr("🌍  Zuletzt gespielte Welten"))
        self.servers_box, self.servers_list = self._section(tr("🖧  Server"))
        cols.addWidget(self.worlds_box, 1)
        cols.addWidget(self.servers_box, 1)
        self.layout_.addLayout(cols)

        self.updates_box, self.updates_list = self._section(tr("⬆  Mod-Updates"))
        self.layout_.addWidget(self.updates_box)

        news_head = QHBoxLayout()
        news_head.addWidget(_label(tr("📰  Minecraft-News"), "h2"))
        news_head.addStretch(1)
        more = QPushButton(tr("Alle News"))
        more.setObjectName("small")
        more.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.minecraft.net/articles")))
        news_head.addWidget(more)
        self.layout_.addLayout(news_head)
        self.news_grid = QGridLayout()
        self.news_grid.setSpacing(14)
        self.layout_.addLayout(self.news_grid)
        self.layout_.addStretch(1)

    def _section(self, title: str):
        box = QFrame()
        box.setObjectName("card")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)
        lay.addWidget(_label(title, "h2"))
        inner = QVBoxLayout()
        inner.setSpacing(6)
        lay.addLayout(inner)
        lay.addStretch(1)
        return box, inner

    # --- Daten -------------------------------------------------------------
    def refresh(self, instances, focus=None) -> None:
        self.instances = instances
        played = sorted((i for i in instances if i.last_played), key=lambda i: i.last_played, reverse=True)
        last_selected = next((i for i in instances if str(i.path) == self.settings.last_instance), None)
        self.focus = focus or (played[0] if played else (last_selected or (instances[0] if instances else None)))
        acc_name = self.display_name
        self.greeting.setText(tr("Willkommen zurück{name}!").format(name=f", {acc_name}" if acc_name else ""))
        self._build_hero()
        self._build_worlds()
        self._build_servers()
        self._build_updates()
        if self._news is None:
            self._news = []
            run_task(lambda: news.minecraft_news(9), self._show_news,
                     lambda err: self._news_error(err))
        else:
            self._show_news(self._news)

    def set_display_name(self, name: str) -> None:
        self.display_name = name

    def show_launcher_update(self, info: dict | None) -> None:
        self._launcher_update = info
        _clear(self.banner_layout)
        if not info:
            self.banner.hide()
            return
        self.banner_layout.addWidget(_label(tr("🎉  ModNest {v} ist verfügbar!").format(v=info["version"]), "cardtitle"), 1)
        btn = QPushButton(tr("Auf GitHub ansehen"))
        btn.setObjectName("primary")
        btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(info["url"])))
        self.banner_layout.addWidget(btn)
        self.banner.show()

    def _build_hero(self) -> None:
        _clear(self.hero_layout)
        inst = self.focus
        if inst is None:
            logo = QLabel()
            logo.setPixmap(logo_pixmap(64))
            self.hero_layout.addWidget(logo)
            col = QVBoxLayout()
            col.addWidget(_label(tr("Los geht's!"), "cardtitle"))
            col.addWidget(_label(tr("Lege deine erste Instanz an oder importiere ein Modpack von Modrinth/CurseForge."),
                                 "cardtext", True))
            self.hero_layout.addLayout(col, 1)
            for text, sig, name in [(tr("＋  Neue Instanz"), self.newInstanceRequested, "primary"),
                                    (tr("📦  Modpack importieren"), self.importRequested, "")]:
                b = QPushButton(text)
                if name:
                    b.setObjectName(name)
                b.clicked.connect(sig)
                self.hero_layout.addWidget(b)
            return
        icon = QLabel()
        icon.setPixmap(instance_icon(inst, 72).pixmap(72, 72))
        self.hero_layout.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(_label(tr("WEITERSPIELEN"), "section"))
        col.addWidget(_label(inst.name, "title"))
        mods = len(inst.mods)
        info = f"{LOADERS.get(inst.loader, inst.loader)} {inst.mc_version}  ·  " + tr("{n} Mods").format(n=mods)
        if inst.playtime:
            info += "  ·  " + tr("{t} gespielt").format(t=duration(inst.playtime))
        if inst.last_played:
            info += "  ·  " + tr("zuletzt {t}").format(t=ago(inst.last_played))
        col.addWidget(_label(info, "cardtext"))
        self.hero_layout.addLayout(col, 1)
        open_btn = QPushButton(tr("Öffnen"))
        open_btn.clicked.connect(lambda: self.openInstance.emit(inst))
        self.hero_layout.addWidget(open_btn)
        play = QPushButton(tr("▶  Spielen"))
        play.setObjectName("primary")
        play.setMinimumHeight(42)
        play.clicked.connect(lambda: self.playRequested.emit(inst))
        self.hero_layout.addWidget(play)

    def _row(self, layout, pix: QPixmap | None, title: str, subtitle: str, button: QPushButton | None,
             extra: QLabel | None = None) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(10)
        icon = QLabel()
        icon.setFixedSize(40, 40)
        if pix is not None and not pix.isNull():
            icon.setPixmap(pix.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        row.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(_label(title, "cardtitle"))
        sub = _label(subtitle, "cardtext")
        col.addWidget(sub)
        row.addLayout(col, 1)
        if extra is not None:
            row.addWidget(extra)
        if button is not None:
            row.addWidget(button)
        layout.addLayout(row)
        return icon

    def _build_worlds(self) -> None:
        _clear(self.worlds_list)
        all_worlds = []
        for inst in self.instances:
            for w in worlds.list_worlds(inst.path):
                all_worlds.append((inst, w))
        all_worlds.sort(key=lambda iw: iw[1].last_played, reverse=True)
        if not all_worlds:
            self.worlds_list.addWidget(_label(tr("Noch keine Welten – starte das Spiel und erstelle eine."), "hint", True))
            return
        for inst, w in all_worlds[:4]:
            pix = QPixmap(str(w.icon)) if w.icon else instance_icon(inst, 40).pixmap(40, 40)
            btn = QPushButton(tr("Beitreten"))
            btn.setObjectName("join")
            btn.clicked.connect(lambda _=False, i=inst, f=w.folder: self.joinWorld.emit(i, f))
            sub = f"{inst.name}  ·  {w.game_mode}  ·  {ago(w.last_played)}" if w.game_mode else \
                f"{inst.name}  ·  {ago(w.last_played)}"
            self._row(self.worlds_list, pix, w.name, sub, btn)

    def _build_servers(self) -> None:
        _clear(self.servers_list)
        seen, entries = set(), []
        ordered = sorted(self.instances, key=lambda i: i.last_played, reverse=True)
        for inst in ordered:
            for s in worlds.list_servers(inst.path):
                if s.address.lower() not in seen:
                    seen.add(s.address.lower())
                    entries.append((inst, s))
        if not entries:
            self.servers_list.addWidget(_label(tr("Noch keine Server – füge im Spiel unter „Mehrspieler“ welche hinzu."),
                                               "hint", True))
            return
        self._req += 1
        req = self._req
        for inst, s in entries[:5]:
            pix = QPixmap()
            if s.icon_png:
                pix.loadFromData(s.icon_png)
            btn = QPushButton(tr("Beitreten"))
            btn.setObjectName("join")
            btn.clicked.connect(lambda _=False, i=inst, a=s.address: self.joinServer.emit(i, a))
            status = _label(tr("prüfe …"), "hint")
            self._row(self.servers_list, pix if not pix.isNull() else None, s.name, f"{s.address}  ·  {inst.name}",
                      btn, status)
            run_task(lambda a=s.address: worlds.ping(a), lambda st, lbl=status: self._status(req, lbl, st))

    def _status(self, req: int, label: QLabel, st) -> None:
        if req != self._req:
            return
        try:
            if st.online:
                label.setObjectName("online")
                label.setText(f"● {st.players}/{st.max_players}  ·  {st.ping_ms} ms")
                label.setToolTip(st.motd + (f"\n{st.version}" if st.version else ""))
            else:
                label.setObjectName("offline")
                label.setText(tr("● offline"))
            label.style().unpolish(label)
            label.style().polish(label)
        except RuntimeError:
            pass  # Karte wurde inzwischen neu aufgebaut

    def _build_updates(self) -> None:
        _clear(self.updates_list)
        inst = self.focus
        if inst is None:
            self.updates_box.hide()
            return
        self.updates_box.show()
        key = str(inst.path)
        if key not in self._updates:
            self._updates[key] = None
            self.updates_list.addWidget(_label(tr("Suche Updates für „{name}“ …").format(name=inst.name), "hint"))
            run_task(lambda: updates.check_updates(inst, self.settings),
                     lambda res, k=key: self._updates_done(k, res),
                     lambda err, k=key: self._updates_done(k, []))
            return
        found = self._updates[key]
        if found is None:
            self.updates_list.addWidget(_label(tr("Suche Updates für „{name}“ …").format(name=inst.name), "hint"))
            return
        head = QHBoxLayout()
        if not found:
            head.addWidget(_label(tr("✔  Alles aktuell in „{name}“.").format(name=inst.name), "hint"), 1)
        else:
            head.addWidget(_label(tr("{n} Update(s) für „{name}“ verfügbar").format(n=len(found), name=inst.name),
                                  "cardtitle"), 1)
            all_btn = QPushButton(tr("Alle aktualisieren"))
            all_btn.setObjectName("primary")
            all_btn.clicked.connect(lambda: self._update_clicked(inst, found))
            head.addWidget(all_btn)
        again = QPushButton(tr("Erneut prüfen"))
        again.setObjectName("small")
        again.clicked.connect(lambda: self.recheck_updates(inst))
        head.addWidget(again)
        self.updates_list.addLayout(head)
        for upd in found[:8]:
            btn = QPushButton(tr("Aktualisieren"))
            btn.setObjectName("small")
            btn.clicked.connect(lambda _=False, u=upd: self._update_clicked(inst, [u]))
            sub = f"{upd.item.version_name or '?'}  →  {upd.release.version_name}"
            icon = self._row(self.updates_list, None, upd.item.name, sub, btn)
            if upd.item.icon_url:
                self.icon_loader.load(upd.item.icon_url, lambda pix, l=icon: self._set_icon(l, pix))
        if len(found) > 8:
            self.updates_list.addWidget(_label(tr("… und {n} weitere").format(n=len(found) - 8), "hint"))

    @staticmethod
    def _set_icon(label: QLabel, pix: QPixmap) -> None:
        try:
            label.setPixmap(pix.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
        except RuntimeError:
            pass  # Zeile wurde inzwischen neu aufgebaut

    def _update_clicked(self, inst, ups: list) -> None:
        self.updateRequested.emit(inst, ups)
        key = str(inst.path)
        done = {id(u) for u in ups}
        self._updates[key] = [u for u in (self._updates.get(key) or []) if id(u) not in done]
        self._build_updates()

    def recheck_updates(self, inst=None) -> None:
        inst = inst or self.focus
        if inst is not None:
            self._updates.pop(str(inst.path), None)
            self._build_updates()

    def _updates_done(self, key: str, result: list) -> None:
        self._updates[key] = result
        try:
            if self.focus is not None and str(self.focus.path) == key:
                self._build_updates()
        except RuntimeError:
            pass

    # --- News --------------------------------------------------------------
    def _news_error(self, err: str) -> None:
        self._news = None
        _clear(self.news_grid)
        self.news_grid.addWidget(_label(tr("News konnten nicht geladen werden ({e}).").format(e=err), "hint"), 0, 0)

    def _show_news(self, items) -> None:
        self._news = items
        try:
            _clear(self.news_grid)
        except RuntimeError:
            return
        for n, item in enumerate(items):
            card = ClickableFrame()
            card.setObjectName("newscard")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            lay = QVBoxLayout(card)
            lay.setContentsMargins(0, 0, 0, 12)
            lay.setSpacing(6)
            img = QLabel()
            img.setFixedHeight(130)
            img.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.setScaledContents(False)
            lay.addWidget(img)
            if item.image_url:
                self.icon_loader.load(item.image_url, lambda pix, l=img: self._set_cover(l, pix))
            meta = QHBoxLayout()
            meta.setContentsMargins(12, 0, 12, 0)
            meta.addWidget(_label(item.tag, "tag"))
            meta.addStretch(1)
            meta.addWidget(_label(item.date, "cardtext"))
            lay.addLayout(meta)
            title = _label(item.title, "cardtitle", True)
            title.setContentsMargins(12, 0, 12, 0)
            lay.addWidget(title)
            text = _label(item.text, "cardtext", True)
            text.setContentsMargins(12, 0, 12, 0)
            text.setMaximumHeight(36)
            lay.addWidget(text)
            card.clicked.connect(lambda it=item: self._open_news(it))
            self.news_grid.addWidget(card, n // 3, n % 3)

    @staticmethod
    def _set_cover(label: QLabel, pix: QPixmap) -> None:
        try:
            w = max(label.width(), 200)
            scaled = pix.scaled(QSize(w, 130), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            x = (scaled.width() - w) // 2
            y = (scaled.height() - 130) // 2
            label.setPixmap(scaled.copy(x, y, w, 130))
        except RuntimeError:
            pass

    def _open_news(self, item) -> None:
        if item.content_path:
            self.patchNotesRequested.emit(item)
        elif item.link:
            QDesktopServices.openUrl(QUrl(item.link))
