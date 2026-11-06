"""Installiert Minecraft + Mod-Loader und startet das Spiel."""
import hashlib
import shlex
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


def jvm_arguments(instance: Instance, settings, ram_override: int = 0) -> list[str]:
    ram = ram_override or instance.ram_mb or settings.ram_mb
    args = [f"-Xmx{ram}M", "-Xms512M"]
    if instance.jvm_args.strip():
        args += shlex.split(instance.jvm_args, posix=False)
    return args


def supports_quick_play(mc_version: str) -> bool:
    """Quick Play (direkt in Welt/Server) gibt es ab Minecraft 1.20 bzw. den neuen Jahresversionen."""
    parts = mc_version.split(".")
    try:
        if parts[0] == "1":
            return int(parts[1]) >= 20
        return int(parts[0]) >= 24
    except (IndexError, ValueError):
        return False


def launch(instance: Instance, settings, account, progress, quick_play: tuple[str, str] | None = None,
           ram_override: int = 0) -> subprocess.Popen:
    """account: ein angemeldetes accounts.Account (Microsoft-Token muss bereits erneuert sein).

    quick_play: ("world", Ordnername) oder ("server", "host:port") – startet direkt dort.
    """
    version_id = install(instance, progress)
    progress("Starte Minecraft …", 0, 0)
    options = {
        "username": account.name,
        "uuid": account.uuid,
        "token": account.mc_token if account.kind == "microsoft" else "0",
        "launcherName": APP_NAME,
        "launcherVersion": APP_VERSION,
        "gameDirectory": str(instance.path),
        "jvmArguments": jvm_arguments(instance, settings, ram_override),
    }
    java = (instance.java_path or settings.java_path).strip()
    if java:
        options["executablePath"] = java
    if quick_play:
        target_kind, target = quick_play
        if supports_quick_play(instance.mc_version):
            options["quickPlayPath"] = "quickPlay/log.json"
            options["quickPlaySingleplayer" if target_kind == "world" else "quickPlayMultiplayer"] = target
        elif target_kind == "server":
            host, _, port = target.rpartition(":")
            options["server"], options["port"] = (host, port) if port.isdigit() else (target, "25565")
    command = mll.command.get_minecraft_command(version_id, str(minecraft_dir()), options)

    log_path = Path(instance.path) / "launcher-log.txt"
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(command, cwd=instance.path, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
