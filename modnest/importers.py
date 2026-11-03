"""Instanzen aus anderen Launchern übernehmen: CurseForge App, Modrinth App, Prism, MultiMC,
ATLauncher und Welten/Einstellungen aus dem offiziellen Minecraft-Launcher.

Die anderen Launcher werden nur gelesen, nie verändert. Ihre Datenbanken werden dafür in einen
temporären Ordner kopiert.
"""
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .i18n import tr
from .instances import Instance, create_instance

# Ordner/Dateien, die nicht mitkopiert werden (Laufzeitdaten der anderen Launcher)
SKIP = {"logs", "crash-reports", ".fabric", ".mixin.out", "natives", ".cache", "debug", "command_history.txt",
        "minecraftinstance.json", "profile.json", "instance.cfg", "mmc-pack.json", "patches", "libraries",
        "launcher_log.txt", ".curseclient", "essential", "downloads"}
# Aus dem offiziellen Launcher nur das hier (der Rest sind Versionen, Assets usw.)
OFFICIAL_KEEP = ("saves", "resourcepacks", "shaderpacks", "screenshots", "options.txt", "optionsof.txt",
                 "optionsshaders.txt", "servers.dat")
LOADER_UIDS = {"net.fabricmc.fabric-loader": "fabric", "org.quiltmc.quilt-loader": "quilt",
               "net.minecraftforge": "forge", "net.neoforged": "neoforge"}


@dataclass
class Found:
    launcher: str
    name: str
    game_dir: Path
    mc_version: str
    loader: str = "vanilla"
    loader_version: str = ""
    icon: Path | None = None
    official: bool = False

    @property
    def label(self) -> str:
        loader = "" if self.loader == "vanilla" else f" · {self.loader.capitalize()}"
        return f"{self.name}  ({self.mc_version}{loader})"


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home())


def _copy_db(path: Path) -> sqlite3.Connection | None:
    """Kopiert eine SQLite-Datenbank (inkl. WAL) und öffnet die Kopie – das Original bleibt unberührt."""
    tmp = Path(tempfile.mkdtemp(prefix="modnest-db-"))
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(path) + suffix)
        if src.exists():
            shutil.copy2(src, tmp / (path.name + suffix))
    try:
        return sqlite3.connect(tmp / path.name)
    except sqlite3.Error:
        return None


def _modrinth() -> list:
    result = []
    for base in (_appdata() / "ModrinthApp", _appdata() / "com.modrinth.theseus"):
        profiles = base / "profiles"
        if not profiles.is_dir():
            continue
        rows = {}
        db = base / "app.db"
        if db.exists():
            con = _copy_db(db)
            if con:
                try:
                    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
                    if "instances" in tables and "instance_content_sets" in tables:
                        q = ("select i.path, i.name, c.game_version, c.loader, c.loader_version, i.icon_path "
                             "from instances i join instance_content_sets c on c.id = i.applied_content_set_id")
                    elif "profiles" in tables:
                        q = "select path, name, game_version, mod_loader, mod_loader_version, icon_path from profiles"
                    else:
                        q = ""
                    for row in con.execute(q) if q else []:
                        rows[row[0]] = row
                except sqlite3.Error:
                    pass
                finally:
                    con.close()
        for folder in sorted(p for p in profiles.iterdir() if p.is_dir()):
            row = rows.get(folder.name)
            if row is None and (folder / "profile.json").exists():   # sehr alte Versionen
                try:
                    meta = json.loads((folder / "profile.json").read_text(encoding="utf-8")).get("metadata", {})
                    row = (folder.name, meta.get("name", folder.name), meta.get("game_version", ""),
                           meta.get("loader", "vanilla"), (meta.get("loader_version") or {}).get("id", ""), None)
                except (OSError, ValueError):
                    row = None
            if row is None or not row[2]:
                continue
            loader = (row[3] or "vanilla").lower()
            result.append(Found("Modrinth App", row[1] or folder.name, folder, row[2],
                                loader if loader in LOADER_UIDS.values() else "vanilla", row[4] or "",
                                Path(row[5]) if row[5] else None))
    return result


def _mmc(launcher: str, base: Path) -> list:
    result = []
    folder = base / "instances"
    if not folder.is_dir():
        return result
    for inst in sorted(p for p in folder.iterdir() if p.is_dir()):
        cfg, pack = inst / "instance.cfg", inst / "mmc-pack.json"
        if not cfg.exists() or not pack.exists():
            continue
        text = cfg.read_text(encoding="utf-8", errors="replace")
        name = next((l[5:] for l in text.splitlines() if l.startswith("name=")), inst.name)
        icon_key = next((l[8:] for l in text.splitlines() if l.startswith("iconKey=")), "")
        try:
            comps = json.loads(pack.read_text(encoding="utf-8")).get("components", [])
        except ValueError:
            continue
        mc = next((c.get("version", "") for c in comps if c.get("uid") == "net.minecraft"), "")
        loader, lv = "vanilla", ""
        for c in comps:
            if c.get("uid") in LOADER_UIDS:
                loader, lv = LOADER_UIDS[c["uid"]], c.get("version", "")
        game = inst / ".minecraft" if (inst / ".minecraft").is_dir() else inst / "minecraft"
        if not mc or not game.is_dir():
            continue
        icon = next((p for p in (inst / f"{icon_key}.png", base / "icons" / f"{icon_key}.png") if icon_key and p.exists()), None)
        result.append(Found(launcher, name, game, mc, loader, lv, icon))
    return result


def _curseforge() -> list:
    result = []
    roots = [Path.home() / "curseforge" / "minecraft" / "Instances"]
    for root in roots:
        if not root.is_dir():
            continue
        for inst in sorted(p for p in root.iterdir() if p.is_dir()):
            meta = inst / "minecraftinstance.json"
            if not meta.exists():
                continue
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except ValueError:
                continue
            base = (data.get("baseModLoader") or {}).get("name", "")   # z.B. "forge-47.2.0"
            loader, lv = "vanilla", ""
            m = re.match(r"(neoforge|forge|fabric|quilt)-([^-]+)", base)
            if m:
                loader, lv = m.group(1), m.group(2)
            icon = inst / "profileImage.png"
            result.append(Found("CurseForge App", data.get("name", inst.name), inst, data.get("gameVersion", ""),
                                loader, lv, icon if icon.exists() else None))
    return result


def _atlauncher() -> list:
    result = []
    for root in (_appdata() / "ATLauncher" / "instances", Path.home() / "ATLauncher" / "instances"):
        if not root.is_dir():
            continue
        for inst in sorted(p for p in root.iterdir() if p.is_dir()):
            meta = inst / "instance.json"
            if not meta.exists():
                continue
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except ValueError:
                continue
            launcher = data.get("launcher") or {}
            lvd = launcher.get("loaderVersion") or {}
            loader = (lvd.get("type") or "vanilla").lower()
            result.append(Found("ATLauncher", launcher.get("name", inst.name), inst, data.get("id", ""),
                                loader if loader in LOADER_UIDS.values() else "vanilla", lvd.get("version", "")))
    return result


def _official() -> list:
    mc = _appdata() / ".minecraft"
    if not (mc / "saves").is_dir() and not (mc / "options.txt").exists():
        return []
    return [Found(tr("Offizieller Launcher"), tr("Minecraft (offizieller Launcher)"), mc, "", official=True)]


def find_all() -> list:
    """Sucht Instanzen in allen bekannten Launchern."""
    found = []
    for fn in (_modrinth, _curseforge, _atlauncher, _official):
        try:
            found += fn()
        except (OSError, ValueError, sqlite3.Error):
            pass
    for launcher, base in (("Prism Launcher", _appdata() / "PrismLauncher"), ("MultiMC", _appdata() / "MultiMC"),
                           ("PolyMC", _appdata() / "PolyMC")):
        try:
            found += _mmc(launcher, base)
        except (OSError, ValueError):
            pass
    return found


def import_found(item: Found, include_worlds: bool, progress=lambda *a: None, latest_release: str = "") -> Instance:
    """Kopiert eine gefundene Instanz nach ModNest. Das Original bleibt unverändert."""
    mc = item.mc_version or latest_release
    if not mc:
        raise ValueError(tr("Die Minecraft-Version von „{name}“ ist unbekannt.").format(name=item.name))
    inst = create_instance(item.name, mc, item.loader, use_defaults=False)
    inst.loader_version = item.loader_version
    try:
        names = OFFICIAL_KEEP if item.official else [p.name for p in item.game_dir.iterdir() if p.name not in SKIP]
        for n, name in enumerate(names, 1):
            src = item.game_dir / name
            if not src.exists() or (name == "saves" and not include_worlds):
                continue
            progress(tr("Kopiere {what} ({n}/{total}) …").format(what=name, n=n, total=len(names)), n, len(names))
            dst = inst.path / name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("*.lock", "session.lock"))
            else:
                shutil.copy2(src, dst)
        if item.icon and item.icon.is_file():
            shutil.copy2(item.icon, inst.path / "icon.png")
            inst.icon = "icon.png"
        inst.sync_with_disk()
        progress(tr("Ergänze Mod-Infos …"), 0, 0)
        try:
            from .modpack import _apply_modrinth_metadata
            _apply_modrinth_metadata(inst)
        except Exception:  # noqa: BLE001 – Infos sind nur Komfort
            pass
        inst.save()
    except BaseException:
        shutil.rmtree(inst.path, ignore_errors=True)
        raise
    return inst
