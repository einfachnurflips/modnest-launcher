"""Backups von Welten und Screenshots, optional in einen Cloud-Ordner (OneDrive, Dropbox, iCloud, Google Drive).

Die Cloud-Programme synchronisieren ihren Ordner selbst – ModNest legt die Backups nur dort ab.
"""
import json
import os
import shutil
import string
import time
import zipfile
from pathlib import Path

from .config import data_dir


def backup_root(settings) -> Path:
    root = Path(settings.backup_dir) if settings.backup_dir else data_dir() / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in " ._-()" else "_" for c in name).strip() or "Unbenannt"


# --- Cloud-Ordner erkennen ------------------------------------------------------
def detect_cloud_folders() -> list[tuple[str, Path]]:
    """(Name, Ordner) aller gefundenen Cloud-Sync-Ordner."""
    found: list[tuple[str, Path]] = []
    home = Path.home()

    def add(name: str, path) -> None:
        if path and Path(path).is_dir() and all(Path(path) != p for _, p in found):
            found.append((name, Path(path)))

    add("OneDrive", os.environ.get("OneDriveConsumer") or os.environ.get("OneDrive"))
    add("OneDrive (Arbeit/Schule)", os.environ.get("OneDriveCommercial"))
    for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")):
        info = Path(base or "") / "Dropbox" / "info.json"
        if info.exists():
            try:
                data = json.loads(info.read_text(encoding="utf-8"))
                for account in data.values():
                    add("Dropbox", account.get("path"))
            except (OSError, ValueError, AttributeError):
                pass
    add("Dropbox", home / "Dropbox")
    add("iCloud Drive", home / "iCloudDrive")
    for letter in string.ascii_uppercase[3:]:
        for sub in ("My Drive", "Meine Ablage"):
            add("Google Drive", Path(f"{letter}:/{sub}"))
    add("Google Drive", home / "Google Drive")
    return found


# --- Screenshots ----------------------------------------------------------------
def backup_screenshots(instance, settings) -> int:
    """Kopiert neue Screenshots einer Instanz in den Backup-Ordner. Gibt die Anzahl neuer Dateien zurück."""
    src = instance.path / "screenshots"
    if not src.is_dir():
        return 0
    dst = backup_root(settings) / "Screenshots" / _safe(instance.name)
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for file in src.iterdir():
        if file.suffix.lower() in (".png", ".jpg", ".jpeg") and not (dst / file.name).exists():
            shutil.copy2(file, dst / file.name)
            copied += 1
    return copied


# --- Welten ---------------------------------------------------------------------
def backup_world(world_path: Path, instance_name: str, settings, keep: int | None = None) -> Path:
    """Packt eine Welt als ZIP mit Zeitstempel und löscht alte Backups über dem Limit."""
    dst_dir = backup_root(settings) / "Welten" / _safe(instance_name) / _safe(world_path.name)
    dst_dir.mkdir(parents=True, exist_ok=True)
    target = dst_dir / f"{_safe(world_path.name)}_{time.strftime('%Y-%m-%d_%H-%M-%S')}.zip"
    tmp = target.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in world_path.rglob("*"):
            if file.is_file() and file.name != "session.lock":
                try:
                    zf.write(file, Path(world_path.name) / file.relative_to(world_path))
                except OSError:
                    continue   # Datei gerade gesperrt – überspringen
    tmp.replace(target)
    keep = keep if keep is not None else settings.backup_keep
    backups = sorted(dst_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[max(keep, 1):]:
        old.unlink(missing_ok=True)
    return target


def backup_changed_worlds(instance, settings, since: float) -> list[str]:
    """Sichert alle Welten, die seit `since` (Unix-Zeit) verändert wurden."""
    saved = []
    saves = instance.path / "saves"
    if not saves.is_dir():
        return saved
    for world in saves.iterdir():
        level = world / "level.dat"
        if level.is_file() and level.stat().st_mtime >= since - 5:
            backup_world(world, instance.name, settings)
            saved.append(world.name)
    return saved


def list_world_backups(settings) -> list[Path]:
    root = backup_root(settings) / "Welten"
    return sorted(root.rglob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []


def restore_world(backup_zip: Path, instance) -> Path:
    """Stellt ein Welt-Backup als neue Welt „<Name> (wiederhergestellt …)“ wieder her."""
    saves = instance.path / "saves"
    saves.mkdir(exist_ok=True)
    with zipfile.ZipFile(backup_zip) as zf:
        top = {n.split("/")[0] for n in zf.namelist() if n.strip("/")}
        folder = next(iter(top)) if len(top) == 1 else backup_zip.stem
        target = saves / f"{folder} (wiederhergestellt {time.strftime('%d.%m. %H-%M')})"
        for member in zf.infolist():
            rel = Path(member.filename)
            if rel.is_absolute() or ".." in rel.parts:
                continue   # Schutz vor manipulierten ZIPs
            parts = rel.parts[1:] if len(top) == 1 else rel.parts
            if not parts:
                continue
            out = target.joinpath(*parts)
            if member.is_dir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    return target
