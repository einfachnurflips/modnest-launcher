"""Tab "Entdecken": Mods, Texturepacks und Shader auf Modrinth und CurseForge suchen und installieren."""
from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..instances import KINDS, Instance
from ..sources import SOURCES, get_source
from .workers import run_task
from ..i18n import tr

AUTO = "__auto__"
PAGE_SIZE = 30
PLACEHOLDERS = {
    "mods": tr("Mods suchen, z.B. Sodium, JEI, Create …"),
    "resourcepacks": tr("Texturepacks suchen, z.B. Faithful, Fresh Animations …"),
    "shaderpacks": tr("Shader suchen, z.B. Complementary, BSL, Bliss …"),
}


def _fmt_downloads(n: int) -> str:
    if n >= 1_000_000:
        return tr("{n} Mio.").format(n=f"{n / 1_000_000:.1f}")
    if n >= 1_000:
        return tr("{n} Tsd.").format(n=f"{n / 1_000:.0f}")
    return str(n)


class SearchPage(QWidget):
    installRequested = Signal(object, object, object)   # Project, Kategorie (None = auto), Release (None = neueste)
    versionPickRequested = Signal(object, object)       # Project, Kategorie
    message = Signal(str)

    def __init__(self, settings, icon_loader, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.icon_loader = icon_loader
        self.instance: Instance | None = None
        self.kind = "mods"
        self.projects = []
        self.offset = 0
        self._search_id = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(10)

        # Art-Auswahl als Pillen
        pills = QHBoxLayout()
        pills.setSpacing(6)
        self.kind_group = QButtonGroup(self)
        for key, icon in (("mods", "🧩"), ("resourcepacks", "🎨"), ("shaderpacks", "✨")):
            btn = QPushButton(f"{icon}  {tr(KINDS[key]['label'])}")
            btn.setObjectName("pill")
            btn.setCheckable(True)
            btn.setChecked(key == "mods")
            btn.clicked.connect(lambda _=False, k=key: self.set_kind(k))
            self.kind_group.addButton(btn)
            pills.addWidget(btn)
        pills.addStretch(1)
        self.source = QComboBox()
        for key, label in SOURCES.items():
            self.source.addItem(label, key)
        self.source.currentIndexChanged.connect(lambda _: self.search())
        pills.addWidget(self.source)
        layout.addLayout(pills)

        bar = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(PLACEHOLDERS["mods"])
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.search)
        bar.addWidget(self.query, 1)
        go = QPushButton(tr("Suchen"))
        go.setObjectName("primary")
        go.clicked.connect(self.search)
        bar.addWidget(go)
        layout.addLayout(bar)

        self.info = QLabel()
        self.info.setObjectName("hint")
        layout.addWidget(self.info)

        self.results = QTreeWidget()
        self.results.setHeaderLabels([tr("Name"), tr("Autor"), tr("Downloads")])
        self.results.setRootIsDecorated(False)
        self.results.setIconSize(QSize(44, 44))
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results.setWordWrap(True)
        self.results.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.results.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.results.itemDoubleClicked.connect(lambda *_: self.install_selected())
        self.results.itemSelectionChanged.connect(self._selection_changed)
        self.results.verticalScrollBar().valueChanged.connect(self._maybe_load_more)
        layout.addWidget(self.results, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel(tr("Kategorie:")))
        self.category = QComboBox()
        self.category.setMinimumWidth(180)
        bottom.addWidget(self.category)
        bottom.addStretch(1)
        page = QPushButton(tr("Projektseite"))
        page.clicked.connect(self.open_page)
        bottom.addWidget(page)
        self.version_btn = QPushButton(tr("⚙  Version wählen …"))
        self.version_btn.setToolTip(tr("Optional: eine bestimmte (z.B. ältere) Version installieren"))
        self.version_btn.clicked.connect(self.pick_version)
        bottom.addWidget(self.version_btn)
        self.install_btn = QPushButton(tr("⬇  Neueste installieren"))
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self.install_selected)
        bottom.addWidget(self.install_btn)
        layout.addLayout(bottom)
        self._selection_changed()

    # --- Zustand -----------------------------------------------------------
    def set_instance(self, instance: Instance | None) -> None:
        changed = instance is not self.instance
        self.instance = instance
        self.refresh_categories()
        if changed:
            self.results.clear()
            self.projects = []
            if instance:
                self.search()

    def set_kind(self, kind: str) -> None:
        if kind == self.kind:
            return
        self.kind = kind
        for btn in self.kind_group.buttons():
            btn.setChecked(tr(KINDS[kind]["label"]) in btn.text())
        self.query.setPlaceholderText(PLACEHOLDERS[kind])
        self.refresh_categories()
        self.search()

    def refresh_categories(self) -> None:
        current = self.category.currentData()
        self.category.clear()
        self.category.addItem(tr("Automatisch erkennen"), AUTO)
        if self.instance:
            for name in self.instance.content[self.kind].category_names():
                self.category.addItem(tr(name), name)
        idx = self.category.findData(current)
        self.category.setCurrentIndex(max(idx, 0))

    def _category(self):
        cat = self.category.currentData()
        return None if cat == AUTO else cat

    def _installed_keys(self) -> set:
        if not self.instance:
            return set()
        return {(m.source, m.project_id) for m in self.instance.content[self.kind].items}

    # --- Suche -------------------------------------------------------------
    def search(self, more: bool = False) -> None:
        if not self.instance:
            return
        if self.kind == "mods" and self.instance.loader == "vanilla":
            self.results.clear()
            self.info.setText(tr("Vanilla-Instanzen können keine Mods laden – Texturepacks gehen aber! "
                              "Für Mods erstelle eine Instanz mit Fabric, Forge o.ä."))
            return
        if not more:
            self.offset = 0
            self.projects = []
            self.results.clear()
        self._search_id += 1
        search_id = self._search_id
        inst = self.instance
        src_key = self.source.currentData()
        query = self.query.text().strip()
        offset = self.offset
        kind = self.kind
        self.info.setText(tr("Suche {what} auf {source} für Minecraft {mc} …").format(
            what=tr(KINDS[kind]["label"]), source=SOURCES[src_key], mc=inst.mc_version))

        def work():
            return get_source(src_key, self.settings).search(query, inst.mc_version, inst.loader, offset,
                                                             PAGE_SIZE, kind)

        run_task(work, lambda res: self._show(search_id, res), lambda err: self._error(search_id, err))

    def _maybe_load_more(self, value: int) -> None:
        bar = self.results.verticalScrollBar()
        if value >= bar.maximum() - 5 and self.projects and len(self.projects) == self.offset + PAGE_SIZE:
            self.offset += PAGE_SIZE
            self.search(more=True)

    def _show(self, search_id: int, projects) -> None:
        if search_id != self._search_id:
            return
        installed = self._installed_keys()
        for proj in projects:
            self.projects.append(proj)
            item = QTreeWidgetItem(["", proj.author, _fmt_downloads(proj.downloads)])
            item.setData(0, Qt.ItemDataRole.UserRole, len(self.projects) - 1)
            item.setToolTip(0, f"<b>{proj.title}</b><br>{proj.description}<br><i>{', '.join(proj.categories)}</i>")
            item.setSizeHint(0, QSize(0, 58))
            self._set_title(item, proj, installed)
            self.results.addTopLevelItem(item)
            if proj.icon_url:
                self.icon_loader.load(proj.icon_url, lambda pix, it=item: it.setIcon(0, QIcon(pix)))
        mc = self.instance.mc_version
        loader = f" / {self.instance.loader}" if self.kind == "mods" else ""
        self.info.setText(tr("{n} Ergebnisse auf {source} – passend zu Minecraft {mc}{loader}. "
                             "Doppelklick installiert die neueste Version.").format(
            n=len(self.projects), source=self.source.currentText(), mc=mc, loader=loader))

    @staticmethod
    def _set_title(item, proj, installed) -> None:
        mark = tr("   ✔ installiert") if (proj.source, proj.project_id) in installed else ""
        item.setText(0, f"{proj.title}{mark}\n{proj.description}")

    def _error(self, search_id: int, err: str) -> None:
        if search_id == self._search_id:
            self.info.setText(f"⚠ {err}")

    # --- Aktionen ----------------------------------------------------------
    def _selected_projects(self):
        return [self.projects[i.data(0, Qt.ItemDataRole.UserRole)] for i in self.results.selectedItems()]

    def _selection_changed(self) -> None:
        count = len(self.results.selectedItems())
        self.install_btn.setEnabled(count > 0)
        self.version_btn.setEnabled(count == 1)
        self.install_btn.setText(tr("⬇  Neueste installieren") if count <= 1 else tr("⬇  {n} installieren").format(n=count))

    def install_selected(self) -> None:
        for proj in self._selected_projects():
            self.installRequested.emit(proj, self._category(), None)

    def pick_version(self) -> None:
        projects = self._selected_projects()
        if len(projects) == 1:
            self.versionPickRequested.emit(projects[0], self._category())

    def open_page(self) -> None:
        for proj in self._selected_projects()[:3]:
            if proj.url:
                QDesktopServices.openUrl(QUrl(proj.url))

    def mark_installed(self) -> None:
        """Aktualisiert die ✔-Markierungen nach einer Installation."""
        installed = self._installed_keys()
        for i in range(self.results.topLevelItemCount()):
            item = self.results.topLevelItem(i)
            self._set_title(item, self.projects[item.data(0, Qt.ItemDataRole.UserRole)], installed)
