"""Verwalten: Server-Liste, Welten (inkl. Datapacks) und komplette Instanz-Backups."""
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from .. import backup, server_watch, worlds
from ..i18n import tr
from ..instances import Instance, _free_path
from ..sources.base import download, session
from ..storage import dir_size, human
from ..trash import move_to_trash
from .fmt import ago
from .workers import run_task


def _safe(fn) -> None:
    try:
        fn()
    except RuntimeError:
        pass


def _button(text: str, slot, tip: str = "", primary: bool = False) -> QPushButton:
    btn = QPushButton(text)
    if tip:
        btn.setToolTip(tip)
    if primary:
        btn.setObjectName("primary")
    btn.clicked.connect(slot)
    return btn


def _pick_instance(parent, instances, current, title: str):
    others = [i for i in instances if i is not current and str(i.path) != str(current.path)]
    if not others:
        QMessageBox.information(parent, title, tr("Es gibt keine andere Instanz."))
        return None
    names = [i.name for i in others]
    name, ok = QInputDialog.getItem(parent, title, tr("Ziel-Instanz:"), names, 0, False)
    return others[names.index(name)] if ok else None


# --- Server ------------------------------------------------------------------------
class ServerEditDialog(QDialog):
    def __init__(self, name: str = "", address: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Server"))
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.name = QLineEdit(name or tr("Minecraft-Server"))
        form.addRow(tr("Name"), self.name)
        self.address = QLineEdit(address)
        self.address.setPlaceholderText(tr("z.B. play.example.net oder 123.45.67.89:25565"))
        form.addRow(tr("Adresse"), self.address)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(lambda: self.accept() if self.address.text().strip() else None)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class ShortcutTargetDialog(QDialog):
    """Vor dem Anlegen einer Server-Verknüpfung: mit welcher Instanz (welchem Modpack) soll beigetreten werden?"""

    def __init__(self, instances, default, server_name: str, address: str, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        from ..instances import LOADERS
        from .icons import instance_icon
        self.server_name = server_name
        self.setWindowTitle(tr("🖥 Verknüpfung – {name}").format(name=server_name))
        self.setMinimumSize(500, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(10)
        title = QLabel(tr("🖥 Verknüpfung zu „{name}“").format(name=server_name))
        title.setObjectName("dialogtitle")
        lay.addWidget(title)
        sub = QLabel(address)
        sub.setObjectName("hint")
        lay.addWidget(sub)
        lay.addWidget(QLabel(tr("Mit welchem Modpack bzw. welcher Instanz soll beigetreten werden?")))
        self.list = QListWidget()
        self.list.setIconSize(QSize(32, 32))
        for inst in instances:
            item = QListWidgetItem(instance_icon(inst, 32), f"{inst.name}\n{LOADERS.get(inst.loader, inst.loader)} "
                                                            f"{inst.mc_version}")
            item.setData(Qt.ItemDataRole.UserRole, inst)
            self.list.addItem(item)
            if inst is default:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        lay.addWidget(self.list, 1)
        form = QFormLayout()
        self.label = QLineEdit()
        self._auto_label = True
        self.label.textEdited.connect(lambda _t: setattr(self, "_auto_label", False))
        form.addRow(tr("Name auf dem Desktop"), self.label)
        lay.addLayout(form)
        self.list.currentItemChanged.connect(lambda *_: self._update_label())
        self._update_label()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(tr("Verknüpfung erstellen"))
        ok.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    @property
    def instance(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_label(self) -> None:
        if self._auto_label and self.instance is not None:
            self.label.setText(f"{self.server_name} ({self.instance.name})")


class WatchDialog(QDialog):
    """Einstellen, wann ModNest zu einem Server Bescheid sagt."""

    def __init__(self, settings, address: str, name: str, tray: bool, parent=None):
        super().__init__(parent)
        self.settings, self.address, self.name = settings, address, name
        cfg = server_watch.get(settings, address)
        self.setWindowTitle(tr("🔔 Benachrichtigungen – {name}").format(name=name or address))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(10)
        title = QLabel(tr("🔔 {name}").format(name=name or address))
        title.setObjectName("dialogtitle")
        lay.addWidget(title)
        sub = QLabel(address)
        sub.setObjectName("hint")
        lay.addWidget(sub)
        self.online = QCheckBox(tr("Bescheid sagen, wenn der Server wieder online ist"))
        self.online.setChecked(bool(cfg.get("online")))
        lay.addWidget(self.online)
        self.anyone = QCheckBox(tr("Bescheid sagen, sobald jemand auf dem Server ist"))
        self.anyone.setChecked(bool(cfg.get("anyone")))
        lay.addWidget(self.anyone)
        lay.addSpacing(6)
        lay.addWidget(QLabel(tr("Bescheid sagen, wenn diese Spieler online kommen:")))
        self.players = QLineEdit(", ".join(cfg.get("players", [])))
        self.players.setPlaceholderText(tr("z.B. Kumpel1, Kumpel2"))
        lay.addWidget(self.players)
        hint = QLabel(tr("ModNest fragt den Server dafür jede Minute ab – genau wie die Serverliste im Spiel. "
                         "Niemand sieht etwas davon. Spielernamen klappen nur, wenn der Server sie mitschickt: "
                         "bei kleinen Servern meist ja, große wie Hypixel zeigen keine echten Namen."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.check = QLabel(tr("prüfe …"))
        self.check.setObjectName("hint")
        self.check.setWordWrap(True)
        lay.addWidget(self.check)
        if not tray:
            warn = QLabel(tr("⚠ Das Symbol im Infobereich ist ausgeschaltet – Meldungen erscheinen dann nur in der "
                             "Statuszeile. Einschalten unter ⚙ Einstellungen."))
            warn.setObjectName("warn")
            warn.setWordWrap(True)
            lay.addWidget(warn)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        run_task(lambda: worlds.ping(address), lambda st: _safe(lambda: self._show(st)))

    def _show(self, st) -> None:
        if not st.online:
            self.check.setText(tr("Gerade offline."))
        elif st.sample:
            self.check.setText(tr("Gerade online: {n} Spieler – der Server zeigt Namen an, z.B. {names}.").format(
                n=st.players, names=", ".join(st.sample[:5])))
        elif st.players:
            self.check.setText(tr("Gerade online: {n} Spieler – der Server zeigt aber keine Namen an, "
                                  "Spieler-Meldungen funktionieren hier nicht.").format(n=st.players))
        else:
            self.check.setText(tr("Gerade online, niemand drauf."))

    def _save(self) -> None:
        server_watch.set_watch(self.settings, self.address, self.name, self.online.isChecked(),
                               self.anyone.isChecked(), server_watch.parse_players(self.players.text()))
        self.accept()


class ServersDialog(QDialog):
    """Server-Liste einer Instanz bearbeiten – landet direkt in servers.dat (auch im Spiel sichtbar)."""

    joinRequested = Signal(object, str)

    def __init__(self, instance, instances, running: bool = False, parent=None, settings=None, tray: bool = True):
        super().__init__(parent)
        self.instance, self.instances = instance, instances
        self.settings, self.tray = settings, tray
        self.entries = worlds.read_server_entries(instance.path)
        self.setWindowTitle(tr("🖧 Server – {name}").format(name=instance.name))
        self.resize(760, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        hint = QLabel(tr("Diese Liste ist dieselbe wie im Spiel unter „Mehrspieler“. Änderungen werden sofort gespeichert."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        if running:
            warn = QLabel(tr("⚠ Minecraft läuft gerade mit dieser Instanz – das Spiel überschreibt die Liste beim Beenden."))
            warn.setWordWrap(True)
            lay.addWidget(warn)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Name"), tr("Adresse"), tr("Status")])
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(32, 32))
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(lambda *_: self._edit())
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for text, slot in ((tr("＋ Hinzufügen"), self._add), (tr("✏ Bearbeiten"), self._edit),
                           (tr("🗑 Entfernen"), self._remove), ("↑", lambda: self._move(-1)), ("↓", lambda: self._move(1)),
                           (tr("⧉ In andere Instanz kopieren …"), self._copy)):
            row.addWidget(_button(text, slot))
        if settings is not None:
            row.addWidget(_button(tr("🔔 Benachrichtigen …"), self._watch,
                                  tr("Bescheid sagen, wenn der Server online ist oder Freunde draufkommen")))
        row.addStretch(1)
        row.addWidget(_button(tr("▶ Beitreten"), self._join, primary=True))
        lay.addLayout(row)
        self._fill()

    def _fill(self, select: int = -1) -> None:
        self.tree.clear()
        self._req = getattr(self, "_req", 0) + 1
        req = self._req
        for i, e in enumerate(self.entries):
            bell = "🔔 " if self.settings is not None and server_watch.is_watched(self.settings, e["ip"]) else ""
            item = QTreeWidgetItem([bell + (e.get("name") or e["ip"]), e["ip"], tr("prüfe …")])
            if e.get("icon"):
                import base64
                pix = QPixmap()
                try:
                    pix.loadFromData(base64.b64decode(e["icon"]))
                    item.setIcon(0, QIcon(pix))
                except ValueError:
                    pass
            self.tree.addTopLevelItem(item)
            run_task(lambda a=e["ip"]: worlds.ping(a), lambda st, it=item: self._status(req, it, st))
        for col in (1, 2):
            self.tree.resizeColumnToContents(col)
        if 0 <= select < self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(select))

    def _status(self, req, item, st) -> None:
        if req != self._req:
            return
        _safe(lambda: item.setText(2, f"● {st.players}/{st.max_players} · {st.ping_ms} ms" if st.online
                                   else tr("● offline")))

    def _watch(self) -> None:
        i = self._index()
        if i < 0:
            QMessageBox.information(self, tr("Server"), tr("Bitte zuerst einen Server auswählen."))
            return
        e = self.entries[i]
        WatchDialog(self.settings, e["ip"], e.get("name") or e["ip"], self.tray, self).exec()
        self._fill(i)

    def _index(self) -> int:
        item = self.tree.currentItem()
        return self.tree.indexOfTopLevelItem(item) if item else -1

    def _save(self, select: int = -1) -> None:
        try:
            worlds.write_server_entries(self.instance.path, self.entries)
        except OSError as exc:
            QMessageBox.warning(self, tr("Server"), str(exc))
        self._fill(select)

    def _add(self) -> None:
        dlg = ServerEditDialog(parent=self)
        if dlg.exec():
            self.entries.append({"name": dlg.name.text().strip(), "ip": dlg.address.text().strip()})
            self._save(len(self.entries) - 1)

    def _edit(self) -> None:
        i = self._index()
        if i < 0:
            return
        e = self.entries[i]
        dlg = ServerEditDialog(e.get("name", ""), e["ip"], self)
        if dlg.exec():
            e["name"], e["ip"] = dlg.name.text().strip(), dlg.address.text().strip()
            self._save(i)

    def _remove(self) -> None:
        i = self._index()
        if i >= 0 and QMessageBox.question(self, tr("Server"), tr("„{name}“ aus der Liste entfernen?").format(
                name=self.entries[i].get("name") or self.entries[i]["ip"])) == QMessageBox.StandardButton.Yes:
            self.entries.pop(i)
            self._save()

    def _move(self, d: int) -> None:
        i = self._index()
        j = i + d
        if i >= 0 and 0 <= j < len(self.entries):
            self.entries[i], self.entries[j] = self.entries[j], self.entries[i]
            self._save(j)

    def _copy(self) -> None:
        i = self._index()
        if i < 0:
            return
        target = _pick_instance(self, self.instances, self.instance, tr("Server kopieren"))
        if target is None:
            return
        entries = worlds.read_server_entries(target.path)
        if any(e["ip"].lower() == self.entries[i]["ip"].lower() for e in entries):
            QMessageBox.information(self, tr("Server kopieren"), tr("Der Server ist dort schon eingetragen."))
            return
        entries.append(dict(self.entries[i]))
        worlds.write_server_entries(target.path, entries)
        QMessageBox.information(self, tr("Server kopieren"), tr("✔ In „{name}“ eingetragen.").format(name=target.name))

    def _join(self) -> None:
        i = self._index()
        if i >= 0:
            self.joinRequested.emit(self.instance, self.entries[i]["ip"])
            self.accept()


# --- Welten ------------------------------------------------------------------------
def _find_world_root(names: list[str]) -> str | None:
    """Ordner im ZIP, der level.dat enthält ("" = ZIP-Wurzel)."""
    candidates = sorted((n[:-len("level.dat")] for n in names if n.endswith("level.dat")), key=len)
    return candidates[0] if candidates else None


def import_world_zip(zip_path: Path, instance) -> Path:
    saves = instance.path / "saves"
    saves.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        root = _find_world_root(names)
        if root is None:
            raise ValueError(tr("In dieser ZIP-Datei ist keine Minecraft-Welt (level.dat fehlt)."))
        base_name = root.strip("/").split("/")[-1] if root.strip("/") else zip_path.stem
        target = saves / base_name
        n = 2
        while target.exists():
            target = saves / f"{base_name} ({n})"
            n += 1
        resolved = target.resolve()
        for member in zf.infolist():
            if not member.filename.startswith(root) or member.is_dir():
                continue
            rel = member.filename[len(root):]
            out = (target / rel).resolve()
            if resolved not in out.parents:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return target


def export_world_zip(world: Path, target: Path) -> Path:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in world.rglob("*"):
            if file.is_file() and file.name != "session.lock":
                try:
                    zf.write(file, (Path(world.name) / file.relative_to(world)).as_posix())
                except OSError:
                    continue
    return target


class WorldsDialog(QDialog):
    playRequested = Signal(object, str)

    def __init__(self, instance, instances, settings, parent=None):
        super().__init__(parent)
        self.instance, self.instances, self.settings = instance, instances, settings
        self.setWindowTitle(tr("🌍 Welten – {name}").format(name=instance.name))
        self.resize(880, 520)
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        hint = QLabel(tr("Tipp: Welt-ZIPs (z.B. heruntergeladene Maps) einfach in dieses Fenster ziehen."))
        hint.setObjectName("hint")
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Welt"), tr("Modus"), tr("Zuletzt gespielt"), tr("Größe")])
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(40, 40))
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tree, 1)
        row1 = QHBoxLayout()
        for text, slot in ((tr("📥 ZIP importieren …"), self._import), (tr("📤 Als ZIP exportieren …"), self._export),
                           (tr("⧉ In andere Instanz kopieren …"), self._copy), (tr("🧩 Datapacks …"), self._datapacks)):
            row1.addWidget(_button(text, slot))
        row1.addStretch(1)
        lay.addLayout(row1)
        row2 = QHBoxLayout()
        for text, slot in ((tr("💾 Jetzt sichern"), self._backup), (tr("✏ Umbenennen …"), self._rename),
                           (tr("📁 Ordner"), self._folder), (tr("🗑 Löschen"), self._delete)):
            row2.addWidget(_button(text, slot))
        row2.addStretch(1)
        row2.addWidget(_button(tr("▶ Spielen"), self._play, primary=True))
        lay.addLayout(row2)
        self.status = QLabel()
        self.status.setObjectName("hint")
        lay.addWidget(self.status)
        self._fill()

    def _fill(self) -> None:
        self.tree.clear()
        self.worlds = sorted(worlds.list_worlds(self.instance.path), key=lambda w: w.last_played, reverse=True)
        for w in self.worlds:
            item = QTreeWidgetItem([w.name, w.game_mode, ago(w.last_played), "…"])
            if w.icon:
                item.setIcon(0, QIcon(str(w.icon)))
            self.tree.addTopLevelItem(item)
            run_task(lambda p=w.path: dir_size(p), lambda size, it=item: _safe(lambda: it.setText(3, human(size))))
        for col in (1, 2, 3):
            self.tree.resizeColumnToContents(col)
        if not self.worlds:
            self.status.setText(tr("Noch keine Welten in dieser Instanz."))

    def _world(self):
        item = self.tree.currentItem()
        if item is None:
            QMessageBox.information(self, tr("Welten"), tr("Bitte zuerst eine Welt auswählen."))
            return None
        return self.worlds[self.tree.indexOfTopLevelItem(item)]

    def _run(self, text, fn, done_text) -> None:
        self.status.setText(text)
        run_task(fn, lambda res: _safe(lambda: (self.status.setText(done_text(res) if callable(done_text) else done_text),
                                                self._fill())),
                 lambda err: _safe(lambda: (self.status.setText(f"⚠ {err}"))))

    def _import(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Welt importieren"), str(Path.home() / "Downloads"),
                                                  tr("Welt (*.zip)"))
        if path:
            inst = self.instance
            self._run(tr("Importiere …"), lambda: import_world_zip(Path(path), inst),
                      lambda t: tr("✔ Welt „{name}“ importiert.").format(name=t.name))

    def _export(self) -> None:
        w = self._world()
        if not w:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Welt exportieren"),
                                              str(Path.home() / "Desktop" / f"{w.path.name}.zip"), tr("Welt (*.zip)"))
        if path:
            self._run(tr("Exportiere …"), lambda: export_world_zip(w.path, Path(path)),
                      lambda t: tr("✔ Gespeichert: {path}").format(path=t))

    def _copy(self) -> None:
        w = self._world()
        if not w:
            return
        target = _pick_instance(self, self.instances, self.instance, tr("Welt kopieren"))
        if target is None:
            return

        def work():
            dst = target.path / "saves" / w.path.name
            n = 2
            while dst.exists():
                dst = target.path / "saves" / f"{w.path.name} ({n})"
                n += 1
            shutil.copytree(w.path, dst, ignore=shutil.ignore_patterns("session.lock"))
            return dst

        self._run(tr("Kopiere …"), work, lambda d: tr("✔ Nach „{name}“ kopiert.").format(name=target.name))

    def _backup(self) -> None:
        w = self._world()
        if w:
            name = self.instance.name
            self._run(tr("Sichere …"), lambda: backup.backup_world(w.path, name, self.settings),
                      tr("✔ Backup angelegt."))

    def _rename(self) -> None:
        w = self._world()
        if not w:
            return
        name, ok = QInputDialog.getText(self, tr("Welt umbenennen"), tr("Neuer Ordnername:"), text=w.path.name)
        name = re.sub(r'[<>:"/\\|?*]', "_", name.strip()) if ok else ""
        if name and name != w.path.name:
            try:
                w.path.rename(w.path.parent / name)
            except OSError as exc:
                QMessageBox.warning(self, tr("Welten"), str(exc))
            self._fill()

    def _folder(self) -> None:
        w = self._world()
        os.startfile(w.path if w else self.instance.path / "saves")  # noqa: S606

    def _delete(self) -> None:
        w = self._world()
        if w and QMessageBox.question(self, tr("Welt löschen"), tr(
                "„{name}“ löschen? Die Welt landet im Windows-Papierkorb.").format(name=w.name)) \
                == QMessageBox.StandardButton.Yes:
            move_to_trash(w.path)
            self._fill()

    def _datapacks(self) -> None:
        w = self._world()
        if w:
            DatapacksDialog(w, self.instance, self).exec()

    def _play(self) -> None:
        w = self._world()
        if w:
            self.playRequested.emit(self.instance, w.path.name)
            self.accept()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.toLocalFile().lower().endswith(".zip"):
                self._import(url.toLocalFile())


class DatapacksDialog(QDialog):
    """Datapacks einer Welt: hinzufügen, entfernen und direkt von Modrinth installieren."""

    def __init__(self, world, instance, parent=None):
        super().__init__(parent)
        self.world, self.instance = world, instance
        self.folder = world.path / "datapacks"
        self.setWindowTitle(tr("🧩 Datapacks – {name}").format(name=world.name))
        self.resize(820, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        head = QLabel(tr("Installiert"))
        head.setObjectName("h2")
        lay.addWidget(head)
        self.installed = QTreeWidget()
        self.installed.setHeaderHidden(True)
        self.installed.setRootIsDecorated(False)
        lay.addWidget(self.installed, 1)
        row = QHBoxLayout()
        row.addWidget(_button(tr("＋ Datei hinzufügen …"), self._add))
        row.addWidget(_button(tr("🗑 Entfernen"), self._remove))
        row.addWidget(_button(tr("📁 Ordner"), lambda: (self.folder.mkdir(exist_ok=True), os.startfile(self.folder))))
        row.addStretch(1)
        lay.addLayout(row)
        head2 = QLabel(tr("Auf Modrinth finden"))
        head2.setObjectName("h2")
        lay.addWidget(head2)
        bar = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(tr("Datapacks suchen, z.B. Terralith, Vanilla Tweaks …"))
        self.query.returnPressed.connect(self._search)
        bar.addWidget(self.query, 1)
        bar.addWidget(_button(tr("Suchen"), self._search, primary=True))
        lay.addLayout(bar)
        self.results = QTreeWidget()
        self.results.setHeaderLabels([tr("Name"), tr("Downloads")])
        self.results.setRootIsDecorated(False)
        self.results.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results.itemDoubleClicked.connect(lambda *_: self._install())
        lay.addWidget(self.results, 1)
        bottom = QHBoxLayout()
        self.status = QLabel(tr("Neue Datapacks wirken beim nächsten Laden der Welt."))
        self.status.setObjectName("hint")
        bottom.addWidget(self.status, 1)
        bottom.addWidget(_button(tr("⬇ Installieren"), self._install, primary=True))
        lay.addLayout(bottom)
        self.hits = []
        self._fill()
        self._search()

    def _fill(self) -> None:
        self.installed.clear()
        if self.folder.is_dir():
            for p in sorted(self.folder.iterdir(), key=lambda p: p.name.lower()):
                if p.suffix.lower() == ".zip" or p.is_dir():
                    item = QTreeWidgetItem([("📦 " if p.is_file() else "📁 ") + p.name])
                    item.setData(0, Qt.ItemDataRole.UserRole, str(p))
                    self.installed.addTopLevelItem(item)

    def _add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Datapack hinzufügen"), str(Path.home() / "Downloads"),
                                                tr("Datapacks (*.zip)"))
        self.folder.mkdir(exist_ok=True)
        for p in paths:
            shutil.copy2(p, self.folder / Path(p).name)
        self._fill()

    def _remove(self) -> None:
        item = self.installed.currentItem()
        if item:
            move_to_trash(Path(item.data(0, Qt.ItemDataRole.UserRole)))
            self._fill()

    def _search(self) -> None:
        query, mc = self.query.text().strip(), self.instance.mc_version
        facets = [["project_type:datapack"]] + ([[f"versions:{mc}"]] if mc else [])

        def work():
            r = session.get("https://api.modrinth.com/v2/search", timeout=20, params={
                "query": query, "facets": json.dumps(facets), "limit": 30,
                "index": "relevance" if query else "downloads"})
            r.raise_for_status()
            return r.json().get("hits", [])

        def done(hits):
            self.hits = hits
            self.results.clear()
            for h in hits:
                item = QTreeWidgetItem([f"{h['title']} – {h.get('description', '')[:90]}", f"{h.get('downloads', 0):,}".replace(",", ".")])
                self.results.addTopLevelItem(item)

        run_task(work, lambda h: _safe(lambda: done(h)), lambda err: _safe(lambda: self.status.setText(f"⚠ {err}")))

    def _install(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        hit = self.hits[self.results.indexOfTopLevelItem(item)]
        mc, folder = self.instance.mc_version, self.folder
        self.status.setText(tr("Lade {name} …").format(name=hit["title"]))

        def work():
            params = {"game_versions": json.dumps([mc])} if mc else {}
            versions = session.get(f"https://api.modrinth.com/v2/project/{hit['project_id']}/version",
                                   params=params, timeout=20).json()
            versions = [v for v in versions if "datapack" in v.get("loaders", [])] or versions
            if not versions:
                raise ValueError(tr("Keine passende Version für Minecraft {mc}.").format(mc=mc))
            files = versions[0]["files"]
            f = next((x for x in files if x.get("primary")), files[0])
            folder.mkdir(exist_ok=True)
            download(f["url"], folder / f["filename"], sha1=(f.get("hashes") or {}).get("sha1", ""))
            return f["filename"]

        run_task(work, lambda name: _safe(lambda: (self.status.setText(tr("✔ {name} installiert.").format(name=name)),
                                                   self._fill())),
                 lambda err: _safe(lambda: self.status.setText(f"⚠ {err}")))


# --- Instanz-Backups ---------------------------------------------------------------
class InstanceBackupsDialog(QDialog):
    restored = Signal(str)        # Pfad der wiederhergestellten Instanz

    def __init__(self, instance, settings, parent=None):
        super().__init__(parent)
        self.instance, self.settings = instance, settings
        self.setWindowTitle(tr("🗄 Instanz-Backups – {name}").format(name=instance.name))
        self.resize(780, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        hint = QLabel(tr("Komplette Sicherungen mit Mods, Configs, Texturepacks, Shadern und Einstellungen – "
                         "auf Wunsch auch mit Welten. Gespeichert im Backup-Ordner unter „Instanzen“."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Datum"), tr("Inhalt"), tr("Anlass"), tr("Größe")])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.worlds = QCheckBox(tr("Welten mitsichern"))
        self.worlds.setChecked(True)
        row.addWidget(self.worlds)
        row.addWidget(_button(tr("💾 Jetzt sichern"), self._create, primary=True))
        row.addStretch(1)
        row.addWidget(_button(tr("Als neue Instanz wiederherstellen"), lambda: self._restore(False)))
        row.addWidget(_button(tr("Instanz ersetzen …"), lambda: self._restore(True)))
        row.addWidget(_button(tr("🗑"), self._delete, tr("Backup löschen")))
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("hint")
        lay.addWidget(self.status)
        self._fill()

    def _fill(self) -> None:
        self.tree.clear()
        self.items = backup.list_instance_backups(self.settings, self.instance.name)
        for path, meta in self.items:
            content = tr("mit Welten") if meta.get("worlds", True) else tr("ohne Welten")
            item = QTreeWidgetItem([time.strftime("%d.%m.%Y %H:%M", time.localtime(meta.get("created", 0))), content,
                                    meta.get("reason") or tr("manuell"), human(meta.get("size", 0))])
            self.tree.addTopLevelItem(item)
        for col in (0, 1, 3):
            self.tree.resizeColumnToContents(col)
        if not self.items:
            self.status.setText(tr("Noch keine Backups."))

    def _selected(self):
        item = self.tree.currentItem()
        return self.items[self.tree.indexOfTopLevelItem(item)] if item else None

    def _create(self) -> None:
        inst, settings, worlds_ = self.instance, self.settings, self.worlds.isChecked()
        self.status.setText(tr("Sichere „{name}“ …").format(name=inst.name))
        run_task(lambda: backup.backup_instance(inst, settings, worlds_, tr("manuell")),
                 lambda p: _safe(lambda: (self.status.setText(tr("✔ Backup angelegt ({size}).").format(
                     size=human(p.stat().st_size))), self._fill())),
                 lambda err: _safe(lambda: self.status.setText(f"⚠ {err}")))

    def _restore(self, replace: bool) -> None:
        sel = self._selected()
        if sel is None:
            return
        path, meta = sel
        inst = self.instance
        if replace:
            if QMessageBox.question(self, tr("Instanz ersetzen"), tr(
                    "„{name}“ durch dieses Backup ersetzen?\n\nDer aktuelle Stand landet im Windows-Papierkorb."
                    "{worlds}").format(name=inst.name, worlds="" if meta.get("worlds", True) else
                                       tr("\n\nAchtung: Dieses Backup enthält keine Welten – sie werden aus dem "
                                          "aktuellen Stand übernommen."))) != QMessageBox.StandardButton.Yes:
                return

        def work():
            if replace:
                keep_saves = None
                if not meta.get("worlds", True) and (inst.path / "saves").exists():
                    keep_saves = inst.path.parent / f".{inst.path.name}-saves-{int(time.time())}"
                    shutil.move(str(inst.path / "saves"), str(keep_saves))
                move_to_trash(inst.path)
                backup.restore_instance_backup(path, inst.path)
                if keep_saves is not None:
                    shutil.move(str(keep_saves), str(inst.path / "saves"))
                return str(inst.path)
            target = _free_path(f"{meta.get('name', inst.name)} ({tr('wiederhergestellt')})")
            backup.restore_instance_backup(path, target)
            restored = Instance.load(target)
            restored.name = f"{meta.get('name', inst.name)} ({tr('wiederhergestellt')})"
            restored.save()
            return str(target)

        self.status.setText(tr("Stelle wieder her …"))
        run_task(work, lambda p: _safe(lambda: (self.restored.emit(p), self.accept())),
                 lambda err: _safe(lambda: self.status.setText(f"⚠ {err}")))

    def _delete(self) -> None:
        sel = self._selected()
        if sel and QMessageBox.question(self, tr("Backup löschen"), tr("Dieses Backup endgültig löschen?")) \
                == QMessageBox.StandardButton.Yes:
            sel[0].unlink(missing_ok=True)
            self._fill()

