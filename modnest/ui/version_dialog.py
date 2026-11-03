"""Versionsauswahl (⚙): alle Versionen eines Projekts anzeigen und eine bestimmte installieren."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from ..instances import Instance
from ..sources import Project, get_source
from .workers import run_task
from ..i18n import tr

TYPE_LABELS = {"release": (tr("Release"), "#22c55e"), "beta": (tr("Beta"), "#f59e0b"), "alpha": (tr("Alpha"), "#ef4444")}


class VersionDialog(QDialog):
    def __init__(self, settings, instance: Instance, project: Project, current_version_id: str = "",
                 icon_loader=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.instance = instance
        self.project = project
        self.current = current_version_id
        self.releases = []
        self.selected = None
        self._request = 0
        self.setWindowTitle(tr("Version wählen – {title}").format(title=project.title))
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        head = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(48, 48)
        head.addWidget(self.icon)
        titles = QVBoxLayout()
        title = QLabel(project.title)
        title.setObjectName("dialogtitle")
        titles.addWidget(title)
        loader = f" · {instance.loader}" if project.kind == "mods" else ""
        sub = QLabel(tr("Passend zu Minecraft {mc}{loader}. Standard ist immer die neueste Version – "
                        "hier kannst du bei Bedarf eine ältere wählen.").format(mc=instance.mc_version, loader=loader))
        sub.setObjectName("hint")
        sub.setWordWrap(True)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        layout.addLayout(head)
        if icon_loader and project.icon_url:
            icon_loader.load(project.icon_url, lambda pix: self.icon.setPixmap(
                pix.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))

        filters = QHBoxLayout()
        self.all_versions = QCheckBox(tr("Auch Versionen für andere Minecraft-Versionen zeigen (kann inkompatibel sein)"))
        self.all_versions.toggled.connect(self.load)
        filters.addWidget(self.all_versions)
        filters.addStretch(1)
        self.betas = QCheckBox(tr("Beta/Alpha zeigen"))
        self.betas.setChecked(True)
        self.betas.toggled.connect(self._fill)
        filters.addWidget(self.betas)
        layout.addLayout(filters)

        self.list = QTreeWidget()
        self.list.setHeaderLabels([tr("Version"), tr("Typ"), "Minecraft", tr("Datum")])
        self.list.setRootIsDecorated(False)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            self.list.header().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.list.itemDoubleClicked.connect(lambda *_: self._accept())
        self.list.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.list, 1)

        self.status = QLabel(tr("Lade Versionen …"))
        self.status.setObjectName("hint")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(tr("Abbrechen"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok = QPushButton(tr("Diese Version installieren"))
        self.ok.setObjectName("primary")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self._accept)
        buttons.addWidget(self.ok)
        layout.addLayout(buttons)
        self.load()

    def load(self) -> None:
        self._request += 1
        req = self._request
        self.list.clear()
        self.status.setText(tr("Lade Versionen …"))
        proj, inst = self.project, self.instance
        mc = "" if self.all_versions.isChecked() else inst.mc_version

        def work():
            return get_source(proj.source, self.settings).list_versions(proj.project_id, mc, inst.loader, proj.kind)

        run_task(work, lambda res: self._loaded(req, res), lambda err: self._failed(req, err))

    def _loaded(self, req, releases) -> None:
        if req != self._request:
            return
        self.releases = releases
        self._fill()

    def _failed(self, req, err) -> None:
        if req == self._request:
            self.status.setText(f"⚠ {err}")

    def _fill(self) -> None:
        try:
            self.list.clear()
        except RuntimeError:
            return
        shown = 0
        latest_marked = False
        for idx, rel in enumerate(self.releases):
            if not self.betas.isChecked() and rel.release_type != "release":
                continue
            label, color = TYPE_LABELS.get(rel.release_type, (rel.release_type, "#94a3b8"))
            name = rel.version_name
            tags = []
            if rel.version_id == self.current:
                tags.append("installiert")
            if not latest_marked and rel.release_type == "release":
                tags.append("neueste")
                latest_marked = True
            if tags:
                name += "   ·  " + ", ".join(tags)
            mc = ", ".join(rel.game_versions[:4]) + (" …" if len(rel.game_versions) > 4 else "")
            item = QTreeWidgetItem([name, label, mc, rel.date[:10]])
            item.setData(0, Qt.ItemDataRole.UserRole, idx)
            item.setForeground(1, QBrush(QColor(color)))
            item.setSizeHint(0, QSize(0, 32))
            if rel.version_id == self.current:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            item.setToolTip(0, rel.filename)
            self.list.addTopLevelItem(item)
            shown += 1
        self.status.setText(tr("{n} Version(en).").format(n=shown) if shown else tr("Keine passenden Versionen gefunden."))

    def _selection_changed(self) -> None:
        items = self.list.selectedItems()
        rel = self.releases[items[0].data(0, Qt.ItemDataRole.UserRole)] if items else None
        self.ok.setEnabled(rel is not None and rel.version_id != self.current)
        if rel is not None and not rel.download_url:
            self.ok.setEnabled(False)
            self.status.setText(tr("Diese Datei darf nur über die Webseite heruntergeladen werden."))

    def _accept(self) -> None:
        items = self.list.selectedItems()
        if not items or not self.ok.isEnabled():
            return
        self.selected = self.releases[items[0].data(0, Qt.ItemDataRole.UserRole)]
        self.accept()
