"""Speicherplatz-Übersicht und Aufräumen."""
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import data_dir, minecraft_dir
from .i18n import tr


def dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


@dataclass
class Cleanup:
    key: str
    label: str
    size: int
    paths: list = field(default_factory=list)


@dataclass
class Report:
    instances: list = field(default_factory=list)     # (Instance, Gesamt, Welten)
    shared: list = field(default_factory=list)        # (Bezeichnung, Größe)
    cleanups: list = field(default_factory=list)      # Cleanup
    total: int = 0


def _old_files(folder: Path, days: int) -> list:
    if not folder.is_dir():
        return []
    limit = time.time() - days * 86400
    return [p for p in folder.iterdir() if p.is_file() and p.stat().st_mtime < limit]


def analyze(instances: list, settings) -> Report:
    rep = Report()
    for inst in instances:
        total = dir_size(inst.path)
        worlds = dir_size(inst.path / "saves")
        rep.instances.append((inst, total, worlds))
        rep.total += total
    mc = minecraft_dir()
    for name, label in (("versions", tr("Minecraft-Versionen")), ("libraries", tr("Bibliotheken")),
                        ("assets", tr("Sounds & Texturen (Assets)")), ("runtime", tr("Java"))):
        size = dir_size(mc / name)
        rep.shared.append((label, size))
        rep.total += size
    from .backup import backup_root
    bsize = dir_size(backup_root(settings))
    rep.shared.append((tr("Backups"), bsize))
    rep.total += bsize

    # Aufräum-Kandidaten
    used = set()
    for inst in instances:
        used.update({inst.version_id, inst.mc_version})
    unused = [p for p in (mc / "versions").iterdir() if p.is_dir() and p.name not in used] \
        if (mc / "versions").is_dir() else []
    # Basis-Versionen, auf denen Loader-Versionen aufbauen, nicht löschen
    keep = set()
    for inst in instances:
        vjson = mc / "versions" / inst.version_id / f"{inst.version_id}.json"
        if inst.version_id and vjson.exists():
            try:
                import json
                parent = json.loads(vjson.read_text(encoding="utf-8")).get("inheritsFrom")
                if parent:
                    keep.add(parent)
            except (OSError, ValueError):
                pass
    unused = [p for p in unused if p.name not in keep]
    if unused:
        rep.cleanups.append(Cleanup("versions", tr("{n} ungenutzte Minecraft-Version(en)").format(n=len(unused)),
                                    sum(dir_size(p) for p in unused), unused))
    logs = []
    for inst in instances:
        logs += _old_files(inst.path / "logs", 14) + _old_files(inst.path / "crash-reports", 30)
        tmp = inst.path / ".modnest-tmp"
        if tmp.exists():
            logs.append(tmp)
    if logs:
        rep.cleanups.append(Cleanup("logs", tr("Alte Logs und Absturzberichte"),
                                    sum(dir_size(p) if p.is_dir() else p.stat().st_size for p in logs), logs))
    caches = [p for p in (data_dir() / "cache",) if p.exists()]
    if caches:
        rep.cleanups.append(Cleanup("cache", tr("Zwischenspeicher"), sum(dir_size(p) for p in caches), caches))
    return rep


def clean(cleanup: Cleanup) -> int:
    freed = 0
    for p in cleanup.paths:
        try:
            if p.is_dir():
                size = dir_size(p)
                shutil.rmtree(p)
            else:
                size = p.stat().st_size
                p.unlink()
            freed += size
        except OSError:
            pass
    return freed
