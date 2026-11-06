"""Tabs "Mods", "Texturepacks", "Shader": installierte Inhalte nach Kategorien, sortierbar per Drag & Drop."""
import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QColorDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from ..categorize import guess_category
from ..instances import FALLBACK_CATEGORY, KINDS, ContentSet, Instance
from .mod_tree import CATEGORY, MOD, ModTree
from .tools_dialogs import CompatDialog
from ..i18n import tr

HINTS = {
    "mods": tr("Ziehe Mods per Drag & Drop in Kategorie und Reihenfolge. ⚙ = andere Version wählen."),
    "resourcepacks": tr("Die Reihenfolge zählt: oben = höchste Priorität. Aktivierte Packs werden beim Start "
                     "in dieser Reihenfolge im Spiel eingeschaltet. ⚙ = andere Version wählen."),
    "shaderpacks": tr("Shader brauchen Iris (Fabric/Quilt/NeoForge) oder OptiFine. Den aktiven Shader wählst du "
                   "im Spiel unter Optionen → Grafik → Shader. ⚙ = andere Version wählen."),
}


class ContentPage(QWidget):
    message = Signal(str)
    versionRequested = Signal(str, object)      # kind, Mod
    irisRequested = Signal()
    perfRequested = Signal()
    searchRequested = Signal(str)               # Suchbegriff für „Entdecken“
    profileApplied = Signal()

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
        self.filter.setPlaceholderText(tr("🔍  {what} filtern …").format(what=tr(info["label"])))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda t: self.tree.set_filter(t))
        bar.addWidget(self.filter, 1)
        for text, tip, slot in [
            (tr("＋  Kategorie"), tr("Neue Kategorie anlegen"), self.add_category),
            ("↑", tr("Auswahl nach oben"), lambda: self.shift_selected(-1)),
            ("↓", tr("Auswahl nach unten"), lambda: self.shift_selected(1)),
            ("⇕", tr("Alle Kategorien auf-/zuklappen"), self.toggle_expand),
            ("📁", tr("Ordner öffnen"), self.open_folder),
        ]:
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            if len(text) <= 2:
                btn.setObjectName("iconbtn")
            bar.addWidget(btn)
        layout.addLayout(bar)

        if kind == "mods":
            tools = QHBoxLayout()
            tools.setSpacing(8)
            for text, tip, slot in [
                (tr("🩺  Prüfen"), tr("Kompatibilitäts-Check: falscher Loader, doppelte Mods, fehlende Abhängigkeiten, "
                                     "bekannte Konflikte"), self.check_compat),
                (tr("⚡  Performance-Paket"), tr("Bewährte Performance-Mods mit einem Klick installieren"),
                 self.perfRequested.emit),
            ]:
                btn = QPushButton(text)
                btn.setObjectName("ghost")
                btn.setToolTip(tip)
                btn.clicked.connect(slot)
                tools.addWidget(btn)
            self.profile_btn = QPushButton(tr("🗂  Profile"))
            self.profile_btn.setObjectName("ghost")
            self.profile_btn.setToolTip(tr("Mod-Profile: gespeicherte An/Aus-Zustände, z.B. „PvP“ oder „Shader-Modus“"))
            self.profile_menu = QMenu(self)
            self.profile_menu.aboutToShow.connect(self._fill_profiles)
            self.profile_btn.setMenu(self.profile_menu)
            tools.addWidget(self.profile_btn)
            tools.addStretch(1)
            layout.addLayout(tools)

        hint_row = QHBoxLayout()
        hint = QLabel(HINTS[kind])
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        hint_row.addWidget(hint, 1)
        if kind == "shaderpacks":
            self.iris_btn = QPushButton(tr("✨ Iris installieren"))
            self.iris_btn.setObjectName("ghost")
            self.iris_btn.clicked.connect(self.irisRequested)
            hint_row.addWidget(self.iris_btn)
        layout.addLayout(hint_row)

        self.tree = ModTree(icon_loader)
        self.tree.setHeaderLabels([tr(info["singular"]), tr("Version"), tr("Quelle"), ""])
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.tree.layoutChanged.connect(self.save_layout)
        self.tree.modToggled.connect(self.toggle_item)
        self.tree.gearClicked.connect(self._gear)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        layout.addWidget(self.tree, 1)

        self.empty = QLabel(tr("Noch keine {what} installiert.\nWechsle zu „Entdecken“, um welche zu finden.").format(
            what=tr(info["label"])))
        self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        find = QShortcut(QKeySequence.StandardKey.Find, self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find.activated.connect(lambda: (self.filter.setFocus(), self.filter.selectAll()))
        delete = QShortcut(QKeySequence.StandardKey.Delete, self.tree, context=Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self._delete_selected)

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
            QMessageBox.warning(self, tr("Fehler"), tr("Datei konnte nicht umbenannt werden:\n{e}").format(e=exc))
        self.rebuild()

    def _gear(self, file: str) -> None:
        item = self.content.find_file(file)
        if item:
            self.versionRequested.emit(self.kind, item)

    # --- Aktionen ----------------------------------------------------------
    def add_category(self) -> None:
        if not self.content:
            return
        name, ok = QInputDialog.getText(self, tr("Neue Kategorie"), tr("Name der Kategorie:"))
        if ok and name.strip():
            if name.strip() in self.content.category_names():
                QMessageBox.information(self, tr("Kategorie"), tr("Diese Kategorie gibt es schon."))
                return
            color = QColorDialog.getColor(QColor("#22c55e"), self, tr("Farbe der Kategorie"))
            self.content.add_category(name.strip(), color.name() if color.isValid() else "#64748b")
            self.rebuild()

    def rename_category(self, name: str) -> None:
        if name == FALLBACK_CATEGORY:
            return
        new, ok = QInputDialog.getText(self, tr("Kategorie umbenennen"), tr("Neuer Name:"), text=name)
        if ok and new.strip() and new.strip() != name:
            if new.strip() in self.content.category_names():
                QMessageBox.information(self, tr("Kategorie"), tr("Diese Kategorie gibt es schon."))
                return
            self.content.rename_category(name, new.strip())
            self.rebuild()

    def recolor_category(self, name: str) -> None:
        color = QColorDialog.getColor(QColor(self.content.category_color(name)), self, tr("Farbe wählen"))
        if color.isValid():
            self.content.set_category_color(name, color.name())
            self.rebuild()

    def delete_category(self, name: str) -> None:
        if QMessageBox.question(self, tr("Kategorie löschen"),
                                tr("Kategorie „{name}“ löschen?\nDie Einträge darin landen in „{fallback}“.").format(
                                    name=name, fallback=tr(FALLBACK_CATEGORY))) \
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
        self.message.emit(tr("{n} Eintrag/Einträge automatisch einsortiert.").format(n=count))

    def remove_items(self, files: list[str]) -> None:
        text = tr("{n} Eintrag/Einträge entfernen? Die Dateien landen im Windows-Papierkorb.").format(n=len(files))
        if QMessageBox.question(self, tr("Entfernen"), text) == QMessageBox.StandardButton.Yes:
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
            menu.addAction(tr("Umbenennen …"), lambda: self.rename_category(name)).setEnabled(name != FALLBACK_CATEGORY)
            menu.addAction(tr("Farbe ändern …"), lambda: self.recolor_category(name))
            menu.addAction(tr("Löschen"), lambda: self.delete_category(name)).setEnabled(name != FALLBACK_CATEGORY)
            menu.addSeparator()
        elif files:
            move = menu.addMenu(tr("In Kategorie verschieben ({n})").format(n=len(files)))
            for cat in self.content.category_names():
                move.addAction(tr(cat), lambda c=cat: self.move_to_category(files, c))
            move.addAction(tr("＋ Neue Kategorie …"), lambda: self._move_to_new_category(files))
            menu.addAction(tr("Aktivieren"), lambda: self._set_enabled(files, True))
            menu.addAction(tr("Deaktivieren"), lambda: self._set_enabled(files, False))
            if len(files) == 1:
                entry = self.content.find_file(files[0])
                if entry and entry.project_id and entry.source != "local":
                    menu.addAction(tr("⚙  Version ändern …"), lambda: self.versionRequested.emit(self.kind, entry))
                if entry and entry.url:
                    menu.addAction(tr("Projektseite öffnen"), lambda: QDesktopServices.openUrl(QUrl(entry.url)))
                if entry and self.content.can_rollback(entry.file):
                    prev = entry.previous.get("version_name") or entry.previous.get("file", "")
                    menu.addAction(tr("↩  Zurück zu {version}").format(version=prev),
                                   lambda: self.rollback(entry))
                if entry:
                    menu.addAction(tr("📝  Notiz bearbeiten …") if entry.note else tr("📝  Notiz hinzufügen …"),
                                   lambda: self.edit_note(entry))
            menu.addSeparator()
            menu.addAction(tr("Entfernen …"), lambda: self.remove_items(files))
            menu.addSeparator()
        menu.addAction(tr("Neue Kategorie …"), self.add_category)
        menu.addAction(tr("Unkategorisierte automatisch einsortieren"), self.auto_sort)
        menu.addAction(tr("Neu laden"), self.refresh)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def rollback(self, entry) -> None:
        try:
            restored = self.content.rollback(entry.file)
        except OSError as exc:
            QMessageBox.warning(self, tr("Zurücksetzen"), str(exc))
            return
        if restored is None:
            return
        self.instance.save()
        self.refresh()
        QMessageBox.information(self, tr("Zurückgesetzt"), tr(
            "„{name}“ ist wieder auf {version}.\n\nDie Version ist jetzt festgelegt (📌), damit sie nicht gleich "
            "wieder als Update angeboten wird. Über „Version ändern“ kannst du das jederzeit aufheben – "
            "oder hier wieder zur neueren Version wechseln.").format(
                name=restored.name or restored.file, version=restored.version_name or restored.file))

    def edit_note(self, entry) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self, tr("Notiz – {name}").format(name=entry.name or entry.file),
            tr("Deine Notiz (z.B. „nicht updaten, crasht mit Iris 1.8“). Leer lassen zum Löschen:"), entry.note)
        if ok:
            entry.note = text.strip()
            self.rebuild()

    def _delete_selected(self) -> None:
        files = [self.tree.key(i) for i in self.tree.selected_of_kind(MOD)]
        if files and self.content:
            self.remove_items(files)

    # --- Kompatibilität & Profile -------------------------------------------
    def check_compat(self) -> None:
        if not self.instance:
            return
        dlg = CompatDialog(self.instance, self)
        dlg.searchRequested.connect(self.searchRequested)
        dlg.exec()
        if dlg.changed:
            self.refresh()

    def _fill_profiles(self) -> None:
        menu = self.profile_menu
        menu.clear()
        if not self.instance:
            return
        profiles = sorted(self.instance.profiles)
        if profiles:
            for name in profiles:
                menu.addAction(tr("▶  {name}").format(name=name), lambda n=name: self.apply_profile(n))
            menu.addSeparator()
        menu.addAction(tr("💾  Aktuellen Zustand als Profil speichern …"), self.save_profile)
        if profiles:
            delete = menu.addMenu(tr("🗑  Profil löschen"))
            for name in profiles:
                delete.addAction(name, lambda n=name: self.delete_profile(n))
        else:
            hint = menu.addAction(tr("Noch keine Profile – schalte Mods an/aus und speichere den Zustand."))
            hint.setEnabled(False)

    def save_profile(self) -> None:
        name, ok = QInputDialog.getText(self, tr("Profil speichern"),
                                        tr("Name des Profils (z.B. PvP, Shader-Modus, Laptop):"))
        if ok and name.strip():
            name = name.strip()
            if name in self.instance.profiles and QMessageBox.question(
                    self, tr("Profil speichern"), tr("Profil „{name}“ überschreiben?").format(name=name)) \
                    != QMessageBox.StandardButton.Yes:
                return
            self.instance.save_profile(name)
            self.message.emit(tr("✔ Profil „{name}“ gespeichert.").format(name=name))

    def apply_profile(self, name: str) -> None:
        try:
            changed = self.instance.apply_profile(name)
        except OSError as exc:
            QMessageBox.warning(self, tr("Profil"), str(exc))
            return
        self.message.emit(tr("✔ Profil „{name}“ aktiv ({n} Änderung(en)).").format(name=name, n=changed))
        self.profileApplied.emit()

    def delete_profile(self, name: str) -> None:
        if QMessageBox.question(self, tr("Profil löschen"), tr("Profil „{name}“ löschen?").format(name=name)) \
                == QMessageBox.StandardButton.Yes:
            self.instance.delete_profile(name)

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
