"""Baumansicht der installierten Mods: Kategorien als Gruppen, alles per Drag & Drop sortierbar."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTreeWidget, QTreeWidgetItem

from ..instances import ContentSet
from . import style
from ..i18n import tr

KIND_ROLE = Qt.ItemDataRole.UserRole
KEY_ROLE = Qt.ItemDataRole.UserRole + 1
CATEGORY, MOD = "category", "mod"
DIP = QAbstractItemView.DropIndicatorPosition

SOURCE_LABELS = {"modrinth": "Modrinth", "curseforge": "CurseForge", "local": tr("Lokal")}


def color_dot(color: str, size: int = 14) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pix)


class ModTree(QTreeWidget):
    layoutChanged = Signal()            # Reihenfolge/Kategorie geändert
    modToggled = Signal(str, bool)      # Datei, aktiviert
    gearClicked = Signal(str)           # Datei – Version ändern

    GEAR_COLUMN = 3

    def __init__(self, icon_loader, parent=None):
        super().__init__(parent)
        self.icon_loader = icon_loader
        self.setHeaderLabels([tr("Name"), tr("Version"), tr("Quelle"), ""])
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.header().resizeSection(3, 44)
        self.header().setStretchLastSection(False)
        self.setMouseTracking(True)
        self.itemClicked.connect(self._on_clicked)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setIconSize(QSize(28, 28))
        self.setAnimated(True)
        self.setUniformRowHeights(False)
        self.itemChanged.connect(self._on_item_changed)
        self._filling = False

    # --- Aufbau ------------------------------------------------------------
    def populate(self, content: ContentSet) -> None:
        expanded = {self.topLevelItem(i).data(0, KEY_ROLE) for i in range(self.topLevelItemCount())
                    if self.topLevelItem(i).isExpanded()}
        first_fill = self.topLevelItemCount() == 0
        self._filling = True
        self.clear()
        for cat in content.categories:
            cat_item = self._make_category(cat["name"], cat.get("color", "#9e9e9e"))
            self.addTopLevelItem(cat_item)
            for mod in content.items:
                if mod.category == cat["name"]:
                    cat_item.addChild(self._make_mod(mod))
            cat_item.setExpanded(first_fill or cat["name"] in expanded)
            cat_item.setFirstColumnSpanned(True)
        self._filling = False
        self.update_counts()

    def _make_category(self, name: str, color: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([tr(name)])
        item.setData(0, KIND_ROLE, CATEGORY)
        item.setData(0, KEY_ROLE, name)
        item.setIcon(0, color_dot(color))
        font = QFont()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        item.setFont(0, font)
        text_color = QColor(color)
        if style.current() == "light":
            text_color = text_color.darker(150)
        item.setForeground(0, QBrush(text_color))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                      | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
        item.setSizeHint(0, QSize(0, 40))
        return item

    def _make_mod(self, mod) -> QTreeWidgetItem:
        version = (mod.version_name or "–") + ("  📌" if mod.pinned else "")
        item = QTreeWidgetItem([mod.name or mod.file, version, SOURCE_LABELS.get(mod.source, mod.source), ""])
        if mod.project_id and mod.source != "local":
            item.setText(self.GEAR_COLUMN, "⚙")
            item.setToolTip(self.GEAR_COLUMN, tr("Version ändern"))
            item.setTextAlignment(self.GEAR_COLUMN, Qt.AlignmentFlag.AlignCenter)
            gear_font = QFont()
            gear_font.setPointSize(gear_font.pointSize() + 3)
            item.setFont(self.GEAR_COLUMN, gear_font)
            item.setForeground(self.GEAR_COLUMN, QBrush(QColor(style.color("muted"))))
        if mod.pinned:
            item.setToolTip(1, tr("Bewusst gewählte Version"))
        item.setData(0, KIND_ROLE, MOD)
        item.setData(0, KEY_ROLE, mod.file)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                      | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked if mod.enabled else Qt.CheckState.Unchecked)
        tip = f"<b>{mod.name}</b><br>{mod.description}<br><i>{mod.file}</i>" if mod.description else mod.file
        item.setToolTip(0, tip)
        if not mod.enabled:
            for col in range(3):
                item.setForeground(col, QBrush(QColor(style.color("disabled"))))
        if mod.icon_url:
            self.icon_loader.load(mod.icon_url, lambda pix, it=item: it.setIcon(0, QIcon(pix)))
        return item

    def update_counts(self) -> None:
        self._filling = True
        for i in range(self.topLevelItemCount()):
            cat = self.topLevelItem(i)
            cat.setText(0, f"{tr(cat.data(0, KEY_ROLE))}   ({cat.childCount()})")
        self._filling = False

    # --- Abfragen ----------------------------------------------------------
    @staticmethod
    def kind(item: QTreeWidgetItem) -> str:
        return item.data(0, KIND_ROLE)

    @staticmethod
    def key(item: QTreeWidgetItem) -> str:
        return item.data(0, KEY_ROLE)

    def export_layout(self) -> tuple[list[str], list[tuple[str, str]]]:
        categories, mods = [], []
        for i in range(self.topLevelItemCount()):
            cat = self.topLevelItem(i)
            categories.append(self.key(cat))
            for j in range(cat.childCount()):
                mods.append((self.key(cat.child(j)), self.key(cat)))
        return categories, mods

    def selected_of_kind(self, kind: str) -> list[QTreeWidgetItem]:
        return [i for i in self._sorted(self.selectedItems()) if self.kind(i) == kind]

    def _sorted(self, items):
        def pos(it):
            parent = it.parent()
            if parent is None:
                return (self.indexOfTopLevelItem(it), -1)
            return (self.indexOfTopLevelItem(parent), parent.indexOfChild(it))
        return sorted(items, key=pos)

    # --- Filter ------------------------------------------------------------
    def set_filter(self, text: str) -> None:
        text = text.lower().strip()
        for i in range(self.topLevelItemCount()):
            cat = self.topLevelItem(i)
            visible = 0
            for j in range(cat.childCount()):
                child = cat.child(j)
                match = not text or text in child.text(0).lower() or text in self.key(child).lower()
                child.setHidden(not match)
                visible += match
            cat.setHidden(bool(text) and visible == 0)
            if text and visible:
                cat.setExpanded(True)

    # --- Drag & Drop -------------------------------------------------------
    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        items = self.selectedItems()
        kinds = {self.kind(i) for i in items}
        target = self.itemAt(event.position().toPoint())
        if len(kinds) != 1 or (kinds == {MOD} and target is None):
            event.ignore()

    def dropEvent(self, event):
        items = self._sorted(self.selectedItems())
        kinds = {self.kind(i) for i in items}
        target = self.itemAt(event.position().toPoint())
        indicator = self.dropIndicatorPosition()
        if len(kinds) != 1 or target in items:
            event.ignore()
            return
        if kinds == {MOD}:
            ok = self._drop_mods(items, target, indicator)
        else:
            ok = self._drop_categories(items, target, indicator)
        # Wir verschieben selbst – Qt soll die Quelle nicht zusätzlich löschen
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        if ok:
            self.update_counts()
            self.layoutChanged.emit()

    def _drop_mods(self, items, target, indicator) -> bool:
        if target is None:
            return False
        if self.kind(target) == CATEGORY:
            parent = target
            if indicator == DIP.AboveItem:
                idx = self.indexOfTopLevelItem(target)
                if idx > 0:
                    parent = self.topLevelItem(idx - 1)
                    index = parent.childCount()
                else:
                    index = 0
            elif indicator == DIP.BelowItem and target.isExpanded():
                index = 0
            else:
                index = parent.childCount()
        else:
            parent = target.parent()
            index = parent.indexOfChild(target) + (0 if indicator == DIP.AboveItem else 1)
        self.move_mods(items, parent, index)
        return True

    def move_mods(self, items, parent: QTreeWidgetItem, index: int) -> None:
        self._filling = True
        for it in items:
            old_parent = it.parent()
            old_index = old_parent.indexOfChild(it)
            if old_parent is parent and old_index < index:
                index -= 1
            old_parent.takeChild(old_index)
        for k, it in enumerate(items):
            parent.insertChild(index + k, it)
        parent.setExpanded(True)
        self._filling = False
        self.clearSelection()
        for it in items:
            it.setSelected(True)

    def _drop_categories(self, items, target, indicator) -> bool:
        if target is None:
            index = self.topLevelItemCount()
        else:
            cat = target if self.kind(target) == CATEGORY else target.parent()
            index = self.indexOfTopLevelItem(cat)
            if indicator == DIP.BelowItem or self.kind(target) == MOD:
                index += 1
        expanded = {id(it): it.isExpanded() for it in items}
        for it in items:
            old_index = self.indexOfTopLevelItem(it)
            if old_index < index:
                index -= 1
            self.takeTopLevelItem(old_index)
        for k, it in enumerate(items):
            self.insertTopLevelItem(index + k, it)
            it.setFirstColumnSpanned(True)
            it.setExpanded(expanded[id(it)])
            it.setSelected(True)
        return True

    def _on_clicked(self, item, column):
        if column == self.GEAR_COLUMN and self.kind(item) == MOD and item.text(self.GEAR_COLUMN):
            self.gearClicked.emit(self.key(item))

    def mouseMoveEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        col = self.columnAt(int(event.position().x()))
        on_gear = item is not None and col == self.GEAR_COLUMN and bool(item.text(self.GEAR_COLUMN))
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if on_gear else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    # --- Checkboxen --------------------------------------------------------
    def _on_item_changed(self, item, column):
        if self._filling or column != 0 or self.kind(item) != MOD:
            return
        self.modToggled.emit(self.key(item), item.checkState(0) == Qt.CheckState.Checked)
