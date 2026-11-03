"""Installiert Minecraft + Mod-Loader und startet das Spiel."""
import hashlib
import subprocess
import sys
import uuid
from pathlib import Path

import minecraft_launcher_lib as mll

from .config import APP_NAME, APP_VERSION, minecraft_dir
from .instances import Instance


def release_versions(include_snapshots: bool = False) -> list[str]:
    return [
        v["id"] for v in mll.utils.get_version_list()
        if v["type"] == "release" or (include_snapshots and v["type"] == "snapshot")
    ]


def offline_uuid(username: str) -> str:
    """Gleiche UUID wie im Offline-Modus von Minecraft (UUID v3 aus "OfflinePlayer:<Name>")."""
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{username}".encode()).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def _is_installed(version_id: str) -> bool:
    return bool(version_id) and (minecraft_dir() / "versions" / version_id / f"{version_id}.json").exists()


def install(instance: Instance, progress) -> str:
    """Stellt sicher, dass Minecraft und der Loader installiert sind. Gibt die Versions-ID zurück."""
    state = {"max": 0}

    def set_status(text):
        progress(text, 0, 0)

    def set_max(value):
        state["max"] = value

    def set_progress(value):
        progress(None, value, state["max"])

    callback = {"setStatus": set_status, "setProgress": set_progress, "setMax": set_max}
    mc_dir = str(minecraft_dir())

    if instance.loader == "vanilla":
        mll.install.install_minecraft_version(instance.mc_version, mc_dir, callback=callback)
        return instance.mc_version

    if _is_installed(instance.version_id):
        # Vanilla-Dateien und Libraries prüfen (schnell, lädt nur Fehlendes nach)
        mll.install.install_minecraft_version(instance.version_id, mc_dir, callback=callback)
        return instance.version_id

    loader = mll.mod_loader.get_mod_loader(instance.loader)
    version_id = loader.install(
        instance.mc_version, mc_dir,
        loader_version=instance.loader_version or None,
        callback=callback,
    )
    instance.version_id = version_id
    instance.save()
    return version_id


def launch(instance: Instance, settings, account, progress) -> subprocess.Popen:
    """account: ein angemeldetes accounts.Account (Microsoft-Token muss bereits erneuert sein)."""
    version_id = install(instance, progress)
    progress("Starte Minecraft …", 0, 0)
    options = {
        "username": account.name,
        "uuid": account.uuid,
        "token": account.mc_token if account.kind == "microsoft" else "0",
        "launcherName": APP_NAME,
        "launcherVersion": APP_VERSION,
        "gameDirectory": str(instance.path),
        "jvmArguments": [f"-Xmx{settings.ram_mb}M", "-Xms512M"],
    }
    if settings.java_path.strip():
        options["executablePath"] = settings.java_path.strip()
    command = mll.command.get_minecraft_command(version_id, str(minecraft_dir()), options)

    log_path = Path(instance.path) / "launcher-log.txt"
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(command, cwd=instance.path, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
