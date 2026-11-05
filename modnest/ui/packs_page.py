"""Seite „Modpacks“: fertige Modpacks von Modrinth, CurseForge, FTB, Technic und ATLauncher installieren."""
import hashlib
import shutil
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QSplitter, QTextBrowser, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import game, packs
from ..i18n import tr
from ..instances import LOADERS
from .fmt import downloads_text
from .project_page import ProjectDialog
from .search_page import SORT_LABELS
from .workers import run_task

TYPE_LABELS = {"release": (tr("Release"), "#22c55e"), "beta": (tr("Beta"), "#f59e0b"), "alpha": (tr("Alpha"), "#ef4444")}
PROVIDER_HINTS = {
    "modrinth": tr("Modrinth: offene Plattform, sehr schnelle Downloads."),
    "curseforge": tr("CurseForge: die größte Auswahl. Braucht einen API-Key (⚙ Einstellungen)."),
    "ftb": tr("Feed The Beast: die offiziellen FTB-Packs (StoneBlock, Skies, OceanBlock …)."),
    "technic": tr("Technic: Klassiker wie Tekkit. Unterstützt werden Packs ab Minecraft 1.12."),
    "atlauncher": tr("ATLauncher: die Packs aus dem ATLauncher (nur neuere Formate)."),
}


class PacksPage(QWidget):
    installRequested = Signal(object, object)      # PackInfo, PackVersion (None = neueste)

    def __init__(self, settings, icon_loader, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.icon_loader = icon_loader
        self.provider_key = "modrinth"
        self.results: list = []
        self.offset = 0
        self._search_id = 0
        self._loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 14)
        layout.setSpacing(10)
        title = QLabel(tr("📦  Modpacks"))
        title.setObjectName("pagetitle")
        layout.addWidget(title)

        pills = QHBoxLayout()
        pills.setSpacing(6)
        self.group = QButtonGroup(self)
        for key, label in packs.PROVIDERS.items():
            btn = QPushButton(label)
            btn.setObjectName("pill")
            btn.setCheckable(True)
            btn.setChecked(key == self.provider_key)
            btn.clicked.connect(lambda _=False, k=key: self.set_provider(k))
            self.group.addButton(btn)
            pills.addWidget(btn)
        pills.addStretch(1)
        layout.addLayout(pills)

        bar = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(tr("Modpacks suchen, z.B. Fabulously Optimized, All the Mods, StoneBlock …"))
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.search)
        bar.addWidget(self.query, 1)
        self.mc = QComboBox()
        self.mc.setMinimumWidth(150)
        self.mc.addItem(tr("Alle Versionen"), "")
        self.mc.currentIndexChanged.connect(lambda _: self.search())
        bar.addWidget(self.mc)
        self.loader = QComboBox()
        self.loader.addItem(tr("Alle Loader"), "")
        for key in packs.LOADERS:
            self.loader.addItem(LOADERS.get(key, key), key)
        self.loader.currentIndexChanged.connect(lambda _: self.search())
        bar.addWidget(self.loader)
        self.sort = QComboBox()
        for key, label in SORT_LABELS.items():
            self.sort.addItem(label, key)
        self.sort.setToolTip(tr("Sortierung (Modrinth und CurseForge)"))
        self.sort.currentIndexChanged.connect(lambda _: self.search())
        bar.addWidget(self.sort)
        go = QPushButton(tr("Suchen"))
        go.setObjectName("primary")
        go.clicked.connect(self.search)
        bar.addWidget(go)
        layout.addLayout(bar)

        self.info = QLabel()
        self.info.setObjectName("hint")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Modpack"), tr("Minecraft"), tr("Autor"), tr("Downloads")])
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(52, 52))
        self.tree.setWordWrap(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_details())
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.verticalScrollBar().valueChanged.connect(self._maybe_more)
        layout.addWidget(self.tree, 1)

        bottom = QHBoxLayout()
        self.provider_hint = QLabel()
        self.provider_hint.setObjectName("hint")
        bottom.addWidget(self.provider_hint, 1)
        page = QPushButton(tr("ℹ  Details"))
        page.setToolTip(tr("Beschreibung, Bilder und Links ansehen (auch per Doppelklick)"))
        page.clicked.connect(self.open_details)
        bottom.addWidget(page)
        self.version_btn = QPushButton(tr("⚙  Version wählen …"))
        self.version_btn.clicked.connect(self.pick_version)
        bottom.addWidget(self.version_btn)
        self.install_btn = QPushButton(tr("⬇  Neueste installieren"))
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self.install_latest)
        bottom.addWidget(self.install_btn)
        layout.addLayout(bottom)
        self._selection_changed()
        self._update_hint()

    # --- Zustand -----------------------------------------------------------
    def activate(self) -> None:
        """Wird beim Öffnen der Seite aufgerufen – lädt beim ersten Mal die beliebtesten Packs."""
        if not self._loaded:
            self._loaded = True
            run_task(game.release_versions, self._fill_versions, lambda err: None)
            self.search()

    def _fill_versions(self, versions) -> None:
        try:
            self.mc.blockSignals(True)
            for v in versions[:60]:
                self.mc.addItem(v, v)
            self.mc.blockSignals(False)
        except RuntimeError:
            pass

    def set_provider(self, key: str) -> None:
        self.provider_key = key
        for btn in self.group.buttons():
            btn.setChecked(btn.text() == packs.PROVIDERS[key])
        self._update_hint()
        self.search()

    def _update_hint(self) -> None:
        self.provider_hint.setText(PROVIDER_HINTS.get(self.provider_key, ""))

    # --- Suche -------------------------------------------------------------
    def search(self, more: bool = False) -> None:
        if not self._loaded:
            return
        if not more:
            self.offset = 0
            self.results = []
            self.tree.clear()
        self._search_id += 1
        sid = self._search_id
        key, query, offset = self.provider_key, self.query.text().strip(), self.offset
        mc, loader = self.mc.currentData() or "", self.loader.currentData() or ""
        sort = self.sort.currentData() if key in ("modrinth", "curseforge") else ""
        self.sort.setEnabled(key in ("modrinth", "curseforge"))
        self.info.setText(tr("Suche Modpacks auf {source} …").format(source=packs.PROVIDERS[key]))
        run_task(lambda: packs.provider(key).search(query, offset, mc, loader, self.settings, sort),
                 lambda res: self._show(sid, res), lambda err: self._error(sid, err))

    def _maybe_more(self, value: int) -> None:
        bar = self.tree.verticalScrollBar()
        if value >= bar.maximum() - 5 and self.results and len(self.results) == self.offset + packs.PAGE_SIZE:
            self.offset += packs.PAGE_SIZE
            self.search(more=True)

    def _show(self, sid: int, found: list) -> None:
        if sid != self._search_id:
            return
        for pack in found:
            self.results.append(pack)
            mcs = pack.mc_versions[:3]
            mc_text = ", ".join(mcs) + (" …" if len(pack.mc_versions) > 3 else "")
            item = QTreeWidgetItem([f"{pack.name}\n{pack.summary[:160]}", mc_text, pack.author,
                                    downloads_text(pack.downloads) if pack.downloads else ""])
            item.setData(0, Qt.ItemDataRole.UserRole, len(self.results) - 1)
            item.setToolTip(0, f"<b>{pack.name}</b><br>{pack.summary}")
            item.setSizeHint(0, QSize(0, 62))
            self.tree.addTopLevelItem(item)
            if pack.icon_url:
                self.icon_loader.load(pack.icon_url, lambda pix, it=item: self._set_icon(it, pix))
        if not self.results:
            self.info.setText(tr("Keine Modpacks gefunden. Probier einen anderen Suchbegriff oder Filter."))
        else:
            self.info.setText(tr("{n} Modpacks auf {source}. Doppelklick zeigt Details.").format(
                n=len(self.results), source=packs.PROVIDERS[self.provider_key]))

    @staticmethod
    def _set_icon(item, pix) -> None:
        try:
            item.setIcon(0, QIcon(pix))
        except RuntimeError:
            pass

    def _error(self, sid: int, err: str) -> None:
        if sid == self._search_id:
            self.info.setText(f"⚠ {err}")

    # --- Aktionen ----------------------------------------------------------
    def _selected(self):
        items = self.tree.selectedItems()
        return self.results[items[0].data(0, Qt.ItemDataRole.UserRole)] if items else None

    def _selection_changed(self) -> None:
        has = self._selected() is not None
        self.install_btn.setEnabled(has)
        self.version_btn.setEnabled(has)

    def install_latest(self) -> None:
        pack = self._selected()
        if pack:
            self.installRequested.emit(pack, None)

    def pick_version(self) -> None:
        pack = self._selected()
        if pack:
            dlg = PackVersionDialog(pack, self.settings, self.icon_loader, self)
            if dlg.exec() and dlg.selected is not None:
                self.installRequested.emit(pack, dlg.selected)

    def open_details(self) -> None:
        pack = self._selected()
        if not pack:
            return
        settings = self.settings
        dlg = ProjectDialog(pack.name, f"{packs.PROVIDERS[pack.provider]} · {pack.author}" if pack.author
                            else packs.PROVIDERS[pack.provider], pack.summary, pack.icon_url, pack.url,
                            lambda: packs.provider(pack.provider).details(pack, settings), self.icon_loader, self)
        dlg.installLatest.connect(lambda: self.installRequested.emit(pack, None))
        dlg.chooseVersion.connect(self.pick_version)
        dlg.exec()

    def open_page(self) -> None:
        pack = self._selected()
        if pack and pack.url:
            QDesktopServices.openUrl(QUrl(pack.url))


class PackVersionDialog(QDialog):
    """Alle Versionen eines Modpacks mit Changelog."""

    def __init__(self, pack, settings, icon_loader=None, parent=None, current: str = "", title: str = ""):
        super().__init__(parent)
        self.pack = pack
        self.settings = settings
        self.versions = []
        self.selected = None
        self.current = current
        self.setWindowTitle(title or tr("Version wählen – {title}").format(title=pack.name))
        self.resize(900, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        head = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(52, 52)
        head.addWidget(self.icon)
        titles = QVBoxLayout()
        name = QLabel(pack.name)
        name.setObjectName("dialogtitle")
        titles.addWidget(name)
        sub = QLabel(f"{packs.PROVIDERS[pack.provider]} · {pack.author}" if pack.author else packs.PROVIDERS[pack.provider])
        sub.setObjectName("hint")
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        self.betas = QCheckBox(tr("Beta/Alpha zeigen"))
        self.betas.setChecked(True)
        self.betas.toggled.connect(self._fill)
        head.addWidget(self.betas)
        layout.addLayout(head)
        if icon_loader and pack.icon_url:
            icon_loader.load(pack.icon_url, lambda pix: self._set_pix(pix))

        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Version"), tr("Minecraft"), tr("Loader"), tr("Typ"), tr("Datum")])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self._accept())
        split.addWidget(self.tree)
        self.changelog = QTextBrowser()
        self.changelog.setOpenExternalLinks(True)
        self.changelog.setPlaceholderText(tr("Changelog der gewählten Version"))
        split.addWidget(self.changelog)
        split.setSizes([520, 340])
        layout.addWidget(split, 1)

        self.status = QLabel(tr("Lade Versionen …"))
        self.status.setObjectName("hint")
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(tr("⬇  Diese Version installieren"))
        self.ok.setEnabled(False)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        run_task(lambda: packs.provider(pack.provider).versions(pack, settings), self._loaded,
                 lambda err: self._safe(lambda: self.status.setText(f"⚠ {err}")))

    def set_ok_text(self, text: str) -> None:
        self.ok.setText(text)

    def _set_pix(self, pix) -> None:
        self._safe(lambda: self.icon.setPixmap(pix.scaled(52, 52, Qt.AspectRatioMode.KeepAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation)))

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except RuntimeError:
            pass  # Dialog schon geschlossen

    def _loaded(self, versions) -> None:
        self.versions = versions
        self._safe(self._fill)

    def _fill(self) -> None:
        self.tree.clear()
        shown = 0
        for i, v in enumerate(self.versions):
            if not self.betas.isChecked() and v.release_type != "release":
                continue
            label, color = TYPE_LABELS.get(v.release_type, TYPE_LABELS["release"])
            name = v.name + (tr("  ★ empfohlen") if v.recommended else "") + (tr("  ← installiert") if v.version_id == self.current else "")
            item = QTreeWidgetItem([name, v.mc_version, LOADERS.get(v.loader, v.loader), label, v.date[:10]])
            item.setForeground(3, QBrush(QColor(color)))
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self.tree.addTopLevelItem(item)
            shown += 1
        for col in range(1, 5):
            self.tree.resizeColumnToContents(col)
        self.status.setText(tr("{n} Versionen").format(n=shown))
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _changed(self) -> None:
        items = self.tree.selectedItems()
        self.ok.setEnabled(bool(items))
        if items:
            v = self.versions[items[0].data(0, Qt.ItemDataRole.UserRole)]
            text = v.changelog.strip()
            if text:
                self.changelog.setMarkdown(text)
            else:
                self.changelog.setPlainText(tr("Kein Changelog verfügbar."))

    def _accept(self) -> None:
        items = self.tree.selectedItems()
        if items:
            self.selected = self.versions[items[0].data(0, Qt.ItemDataRole.UserRole)]
            self.accept()


class ManualDownloadDialog(QDialog):
    """Hilft bei Dateien, die nur über die Webseite geladen werden dürfen.

    Du klickst auf „Öffnen“, lädst die Datei im Browser herunter – ModNest findet sie automatisch
    im Downloads-Ordner und verschiebt sie an die richtige Stelle.
    """

    def __init__(self, instance, files: list, parent=None):
        super().__init__(parent)
        self.instance = instance
        self.files = list(files)
        self.downloads = Path.home() / "Downloads"
        self.setWindowTitle(tr("Fast fertig – manuelle Downloads"))
        self.resize(760, 460)
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        intro = QLabel(tr("Die Autoren dieser Dateien erlauben keinen automatischen Download. "
                          "Klick jeweils auf „Öffnen“ und lade die Datei im Browser herunter – "
                          "ModNest erkennt sie im Downloads-Ordner und baut sie automatisch ein. "
                          "Du kannst Dateien auch einfach in dieses Fenster ziehen."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Datei"), tr("Status"), ""])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.folder_label = QLabel()
        self.folder_label.setObjectName("hint")
        row.addWidget(self.folder_label, 1)
        change = QPushButton(tr("Anderer Downloads-Ordner …"))
        change.clicked.connect(self._choose_folder)
        row.addWidget(change)
        self.done_btn = QPushButton(tr("Fertig"))
        self.done_btn.setObjectName("primary")
        self.done_btn.clicked.connect(self.accept)
        row.addWidget(self.done_btn)
        layout.addLayout(row)
        self.items = []
        for f in self.files:
            item = QTreeWidgetItem([f.name, tr("❌ fehlt"), ""])
            item.setToolTip(0, f.filename)
            self.tree.addTopLevelItem(item)
            btn = QPushButton(tr("Öffnen"))
            btn.setObjectName("small")
            btn.setEnabled(bool(f.url))
            btn.clicked.connect(lambda _=False, u=f.url: QDesktopServices.openUrl(QUrl(u)))
            self.tree.setItemWidget(item, 2, btn)
            self.items.append(item)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setStretchLastSection(False)
        self.tree.setColumnWidth(2, 110)
        self._update_folder()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._scan)
        self.timer.start(2000)
        self._scan()

    def _update_folder(self) -> None:
        self.folder_label.setText(tr("Überwacht: {path}").format(path=self.downloads))

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("Downloads-Ordner wählen"), str(self.downloads))
        if path:
            self.downloads = Path(path)
            self._update_folder()
            self._scan()

    def _target(self, f) -> Path:
        return self.instance.path / f.folder / f.filename

    def _take(self, f, source: Path) -> bool:
        if f.sha1:
            digest = hashlib.sha1(source.read_bytes()).hexdigest()
            if digest.lower() != f.sha1.lower():
                return False
        target = self._target(f)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return True

    def _scan(self) -> None:
        missing = 0
        for f, item in zip(self.files, self.items):
            if self._target(f).exists():
                item.setText(1, tr("✔ eingebaut"))
                continue
            candidate = self.downloads / f.filename
            if candidate.is_file():
                try:
                    if self._take(f, candidate):
                        item.setText(1, tr("✔ eingebaut"))
                        continue
                    item.setText(1, tr("⚠ falsche Datei"))
                except OSError:
                    pass
            missing += 1
        self.done_btn.setText(tr("Fertig") if not missing else tr("Später ({n} fehlen)").format(n=missing))
        if not missing:
            self.timer.stop()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            for f in self.files:
                if path.name == f.filename and not self._target(f).exists():
                    try:
                        self._take(f, path)
                    except OSError:
                        pass
        self._scan()

    def done(self, result) -> None:
        self.timer.stop()
        self.instance.sync_with_disk()
        self.instance.save()
        super().done(result)
