"""Tabs "Mods", "Texturepacks", "Shader": installierte Inhalte nach Kategorien, sortierbar per Drag & Drop."""
import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QColorDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from ..categorize import guess_category
from ..instances import FALLBACK_CATEGORY, KINDS, ContentSet, Instance
from .mod_tree import CATEGORY, MOD, ModTree

HINTS = {
    "mods": "Ziehe Mods per Drag & Drop in Kategorie und Reihenfolge. ⚙ = andere Version wählen.",
    "resourcepacks": "Die Reihenfolge zählt: oben = höchste Priorität. Aktivierte Packs werden beim Start "
                     "in dieser Reihenfolge im Spiel eingeschaltet. ⚙ = andere Version wählen.",
    "shaderpacks": "Shader brauchen Iris (Fabric/Quilt/NeoForge) oder OptiFine. Den aktiven Shader wählst du "
                   "im Spiel unter Optionen → Grafik → Shader. ⚙ = andere Version wählen.",
}


class ContentPage(QWidget):
    message = Signal(str)
    versionRequested = Signal(str, object)      # kind, Mod
    irisRequested = Signal()

    def __init__(self, kind: str, icon_loader, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.instance: Instance | None = None
        info = KINDS[kind]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(f"🔍  {info['label']} filtern …")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda t: self.tree.set_filter(t))
        bar.addWidget(self.filter, 1)
        for text, tip, slot in [
            ("＋  Kategorie", "Neue Kategorie anlegen", self.add_category),
            ("↑", "Auswahl nach oben", lambda: self.shift_selected(-1)),
            ("↓", "Auswahl nach unten", lambda: self.shift_selected(1)),
            ("⇕", "Alle Kategorien auf-/zuklappen", self.toggle_expand),
            ("📁", "Ordner öffnen", self.open_folder),
        ]:
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            if len(text) <= 2:
                btn.setObjectName("iconbtn")
            bar.addWidget(btn)
        layout.addLayout(bar)

        hint_row = QHBoxLayout()
        hint = QLabel(HINTS[kind])
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        hint_row.addWidget(hint, 1)
        if kind == "shaderpacks":
            self.iris_btn = QPushButton("✨ Iris installieren")
            self.iris_btn.setObjectName("ghost")
            self.iris_btn.clicked.connect(self.irisRequested)
            hint_row.addWidget(self.iris_btn)
        layout.addLayout(hint_row)

        self.tree = ModTree(icon_loader)
        self.tree.setHeaderLabels([info["singular"], "Version", "Quelle", ""])
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.tree.layoutChanged.connect(self.save_layout)
        self.tree.modToggled.connect(self.toggle_item)
        self.tree.gearClicked.connect(self._gear)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        layout.addWidget(self.tree, 1)

        self.empty = QLabel(f"Noch keine {info['label']} installiert.\nWechsle zu „Entdecken“, um welche zu finden.")
        self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

    # --- Daten -------------------------------------------------------------
    @property
    def content(self) -> ContentSet | None:
        return self.instance.content[self.kind] if self.instance else None

    def set_instance(self, instance: Instance | None) -> None:
        self.instance = instance
        self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        if self.content:
            self.content.sync_with_disk()
            self.tree.populate(self.content)
            self.tree.set_filter(self.filter.text())
        self._update_empty()
        if self.kind == "shaderpacks":
            self._update_iris()

    def _update_empty(self) -> None:
        has_items = bool(self.content and self.content.items)
        self.empty.setVisible(not has_items)

    def _update_iris(self) -> None:
        inst = self.instance
        show = bool(inst and inst.loader in ("fabric", "quilt", "neoforge")
                    and not any("iris" in m.name.lower() or "oculus" in m.name.lower() for m in inst.mods))
        self.iris_btn.setVisible(show)

    def save_layout(self) -> None:
        if not self.content:
            return
        cats, items = self.tree.export_layout()
        self.content.apply_layout(cats, items)
        self.instance.save()

    def rebuild(self) -> None:
        self.instance.save()
        self.tree.populate(self.content)
        self.tree.set_filter(self.filter.text())
        self._update_empty()

    def toggle_item(self, file: str, enabled: bool) -> None:
        try:
            self.content.set_enabled(file, enabled)
        except OSError as exc:
            QMessageBox.warning(self, "Fehler", f"Datei konnte nicht umbenannt werden:\n{exc}")
        self.rebuild()

    def _gear(self, file: str) -> None:
        item = self.content.find_file(file)
        if item:
            self.versionRequested.emit(self.kind, item)

    # --- Aktionen ----------------------------------------------------------
    def add_category(self) -> None:
        if not self.content:
            return
        name, ok = QInputDialog.getText(self, "Neue Kategorie", "Name der Kategorie:")
        if ok and name.strip():
            if name.strip() in self.content.category_names():
                QMessageBox.information(self, "Kategorie", "Diese Kategorie gibt es schon.")
                return
            color = QColorDialog.getColor(QColor("#22c55e"), self, "Farbe der Kategorie")
            self.content.add_category(name.strip(), color.name() if color.isValid() else "#64748b")
            self.rebuild()

    def rename_category(self, name: str) -> None:
        if name == FALLBACK_CATEGORY:
            return
        new, ok = QInputDialog.getText(self, "Kategorie umbenennen", "Neuer Name:", text=name)
        if ok and new.strip() and new.strip() != name:
            if new.strip() in self.content.category_names():
                QMessageBox.information(self, "Kategorie", "Diese Kategorie gibt es schon.")
                return
            self.content.rename_category(name, new.strip())
            self.rebuild()

    def recolor_category(self, name: str) -> None:
        color = QColorDialog.getColor(QColor(self.content.category_color(name)), self, "Farbe wählen")
        if color.isValid():
            self.content.set_category_color(name, color.name())
            self.rebuild()

    def delete_category(self, name: str) -> None:
        if QMessageBox.question(self, "Kategorie löschen",
                                f"Kategorie „{name}“ löschen?\nDie Einträge darin landen in „{FALLBACK_CATEGORY}“.") \
                == QMessageBox.StandardButton.Yes:
            self.content.delete_category(name)
            self.rebuild()

    def move_to_category(self, files: list[str], category: str) -> None:
        items = self.content.items
        for m in items:
            if m.file in files:
                m.category = category
        moved = [m for m in items if m.file in files]
        self.content.items = [m for m in items if m.file not in files] + moved
        self.rebuild()

    def auto_sort(self) -> None:
        """Ordnet unkategorisierte Einträge anhand ihres Namens grob zu."""
        names = self.content.category_names()
        count = 0
        for m in self.content.items:
            if m.category == FALLBACK_CATEGORY:
                guess = guess_category([m.name, m.description], names, self.kind)
                if guess != FALLBACK_CATEGORY:
                    m.category = guess
                    count += 1
        self.rebuild()
        self.message.emit(f"{count} Eintrag/Einträge automatisch einsortiert.")

    def remove_items(self, files: list[str]) -> None:
        text = f"{len(files)} Eintrag/Einträge wirklich entfernen? Die Dateien werden gelöscht."
        if QMessageBox.question(self, "Entfernen", text) == QMessageBox.StandardButton.Yes:
            for f in files:
                self.content.remove(f)
            self.rebuild()

    def shift_selected(self, direction: int) -> None:
        mods = self.tree.selected_of_kind(MOD)
        cats = self.tree.selected_of_kind(CATEGORY)
        if mods:
            parent = mods[0].parent()
            if any(m.parent() is not parent for m in mods):
                return
            first = parent.indexOfChild(mods[0])
            last = parent.indexOfChild(mods[-1])
            if direction < 0 and first > 0:
                self.tree.move_mods(mods, parent, first - 1)
            elif direction > 0 and last < parent.childCount() - 1:
                self.tree.move_mods(mods, parent, last + 2)
            else:
                return
        elif len(cats) == 1:
            idx = self.tree.indexOfTopLevelItem(cats[0])
            new = idx + direction
            if not 0 <= new < self.tree.topLevelItemCount():
                return
            expanded = cats[0].isExpanded()
            self.tree.takeTopLevelItem(idx)
            self.tree.insertTopLevelItem(new, cats[0])
            cats[0].setFirstColumnSpanned(True)
            cats[0].setExpanded(expanded)
            cats[0].setSelected(True)
        else:
            return
        self.tree.update_counts()
        self.save_layout()

    def toggle_expand(self) -> None:
        any_collapsed = any(not self.tree.topLevelItem(i).isExpanded() for i in range(self.tree.topLevelItemCount()))
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(any_collapsed)

    def open_folder(self) -> None:
        if self.content:
            os.startfile(self.content.folder)  # noqa: S606 – nur Windows-Explorer öffnen

    def _double_clicked(self, item, column):
        if self.tree.kind(item) == CATEGORY:
            self.rename_category(self.tree.key(item))

    # --- Kontextmenü -------------------------------------------------------
    def context_menu(self, pos) -> None:
        if not self.content:
            return
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        files = [self.tree.key(i) for i in self.tree.selected_of_kind(MOD)]
        if item is not None and self.tree.kind(item) == CATEGORY:
            name = self.tree.key(item)
            menu.addAction("Umbenennen …", lambda: self.rename_category(name)).setEnabled(name != FALLBACK_CATEGORY)
            menu.addAction("Farbe ändern …", lambda: self.recolor_category(name))
            menu.addAction("Löschen", lambda: self.delete_category(name)).setEnabled(name != FALLBACK_CATEGORY)
            menu.addSeparator()
        elif files:
            move = menu.addMenu(f"In Kategorie verschieben ({len(files)})")
            for cat in self.content.category_names():
                move.addAction(cat, lambda c=cat: self.move_to_category(files, c))
            move.addAction("＋ Neue Kategorie …", lambda: self._move_to_new_category(files))
            menu.addAction("Aktivieren", lambda: self._set_enabled(files, True))
            menu.addAction("Deaktivieren", lambda: self._set_enabled(files, False))
            if len(files) == 1:
                entry = self.content.find_file(files[0])
                if entry and entry.project_id and entry.source != "local":
                    menu.addAction("⚙  Version ändern …", lambda: self.versionRequested.emit(self.kind, entry))
                if entry and entry.url:
                    menu.addAction("Projektseite öffnen", lambda: QDesktopServices.openUrl(QUrl(entry.url)))
            menu.addSeparator()
            menu.addAction("Entfernen …", lambda: self.remove_items(files))
            menu.addSeparator()
        menu.addAction("Neue Kategorie …", self.add_category)
        menu.addAction("Unkategorisierte automatisch einsortieren", self.auto_sort)
        menu.addAction("Neu laden", self.refresh)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _move_to_new_category(self, files: list[str]) -> None:
        before = set(self.content.category_names())
        self.add_category()
        created = [c for c in self.content.category_names() if c not in before]
        if created:
            self.move_to_category(files, created[0])

    def _set_enabled(self, files: list[str], enabled: bool) -> None:
        for f in files:
            self.content.set_enabled(f, enabled)
        self.rebuild()
