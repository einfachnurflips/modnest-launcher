"""Instanzliste der Seitenleiste: per Drag & Drop sortierbar, mit auf-/zuklappbaren Ordnern."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from ..i18n import tr
from ..instances import LOADERS
from .fmt import ago
from .icons import instance_icon

ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_KEY = Qt.ItemDataRole.UserRole + 1


class InstanceList(QListWidget):
    instanceActivated = Signal(object)        # Instance
    layoutChanged = Signal(list)              # [(Ordnername der Instanz, Gruppe)]
    groupToggled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("instances")
        self.setIconSize(QSize(38, 38))
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.by_path: dict[str, object] = {}
        self.itemClicked.connect(self._clicked)
        self.currentItemChanged.connect(self._current_changed)

    # --- Aufbau ------------------------------------------------------------
    def populate(self, instances: list, groups: list[str], collapsed: set[str]) -> None:
        """instances: bereits sortiert. groups: Reihenfolge der Ordner."""
        self.blockSignals(True)
        self.clear()
        self.by_path = {str(i.path): i for i in instances}
        loose = [i for i in instances if not i.group or i.group not in groups]
        for inst in loose:
            self._add_instance(inst, False)
        for group in groups:
            members = [i for i in instances if i.group == group]
            self._add_group(group, len(members), group in collapsed)
            for inst in members:
                self._add_instance(inst, group in collapsed)
        self.blockSignals(False)

    def _add_group(self, name: str, count: int, closed: bool) -> None:
        arrow = "▸" if closed else "▾"
        item = QListWidgetItem(f"{arrow}  📁  {name}   ({count})")
        item.setData(ROLE_KIND, "group")
        item.setData(ROLE_KEY, name)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setSizeHint(QSize(0, 30))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        self.addItem(item)

    def _add_instance(self, inst, hidden: bool) -> None:
        sub = f"{LOADERS.get(inst.loader, inst.loader)} · {inst.mc_version}"
        item = QListWidgetItem(instance_icon(inst, 38), f"{inst.name}\n{sub}")
        item.setData(ROLE_KIND, "instance")
        item.setData(ROLE_KEY, str(inst.path))
        item.setSizeHint(QSize(0, 58))
        item.setToolTip(tr("Zuletzt gespielt: {t}").format(t=ago(inst.last_played)))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
        self.addItem(item)
        item.setHidden(hidden)

    def update_instance(self, inst) -> None:
        item = self.item_for(inst)
        if item is not None:
            item.setIcon(instance_icon(inst, 38))
            item.setText(f"{inst.name}\n{LOADERS.get(inst.loader, inst.loader)} · {inst.mc_version}")

    # --- Zugriff -----------------------------------------------------------
    def instance_at(self, item):
        if item is None or item.data(ROLE_KIND) != "instance":
            return None
        return self.by_path.get(item.data(ROLE_KEY))

    def item_for(self, inst):
        key = str(inst.path)
        for i in range(self.count()):
            it = self.item(i)
            if it.data(ROLE_KIND) == "instance" and it.data(ROLE_KEY) == key:
                return it
        return None

    def select(self, inst) -> None:
        item = self.item_for(inst)
        if item is not None:
            self.blockSignals(True)
            self.setCurrentItem(item)
            item.setSelected(True)
            self.blockSignals(False)

    # --- Ereignisse --------------------------------------------------------
    def _clicked(self, item) -> None:
        if item.data(ROLE_KIND) == "group":
            self.groupToggled.emit(item.data(ROLE_KEY))
            return
        inst = self.instance_at(item)
        if inst is not None:
            self.instanceActivated.emit(inst)

    def _current_changed(self, current, previous) -> None:
        inst = self.instance_at(current)
        if inst is not None:
            self.instanceActivated.emit(inst)

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        # Gruppenzugehörigkeit ergibt sich aus der Position: alles unter einem Ordner gehört dazu
        layout, group = [], ""
        for i in range(self.count()):
            it = self.item(i)
            if it.data(ROLE_KIND) == "group":
                group = it.data(ROLE_KEY)
            else:
                layout.append((it.data(ROLE_KEY), group))
        self.layoutChanged.emit(layout)
