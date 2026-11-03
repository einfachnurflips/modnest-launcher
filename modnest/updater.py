"""Selbst-Update für die installierte .exe-Version und Deinstallation."""
import ctypes
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .i18n import tr
from .sources.base import download

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_installed_exe() -> bool:
    return bool(getattr(sys, "frozen", False))


def download_setup(info: dict, progress=lambda *a: None) -> Path:
    url = info.get("setup_url")
    if not url:
        raise OSError(tr("Für diese Version gibt es kein Setup zum Herunterladen."))
    target = Path(tempfile.mkdtemp(prefix="modnest-update-")) / Path(url).name
    progress(tr("Lade ModNest {v} …").format(v=info["version"]), 0, 100)
    download(url, target, lambda done, total: progress(tr("Lade ModNest {v} …").format(v=info["version"]),
                                                       done * 100 // total, 100))
    expected = (info.get("sha256") or "").lower()
    if expected:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != expected:
            target.unlink(missing_ok=True)
            raise OSError(tr("Die heruntergeladene Datei ist beschädigt (Prüfsumme falsch)."))
    return target


def run_setup(setup: Path) -> None:
    """Startet das Setup im Update-Modus. Der Launcher muss sich danach beenden."""
    subprocess.Popen([str(setup), "--silent"], cwd=str(setup.parent), creationflags=subprocess.DETACHED_PROCESS)


def uninstall() -> int:
    """Wird über „Apps & Features“ aufgerufen (ModNest.exe --uninstall)."""
    user32 = ctypes.windll.user32
    if user32.MessageBoxW(None, tr("ModNest wirklich deinstallieren?"), "ModNest", 0x4 | 0x20) != 6:
        return 1
    delete_data = user32.MessageBoxW(None, tr(
        "Sollen auch deine Instanzen, Welten, Screenshots und Einstellungen gelöscht werden?\n\n"
        "„Nein“ behält sie (empfohlen) – bei einer späteren Neuinstallation ist dann alles wieder da."),
        "ModNest", 0x4 | 0x30 | 0x100) == 6
    install_dir = Path(sys.executable).resolve().parent
    script = (
        "$desk = [Environment]::GetFolderPath('Desktop'); $start = [Environment]::GetFolderPath('Programs'); "
        "Remove-Item -LiteralPath ($desk + '\\ModNest.lnk'), ($start + '\\ModNest.lnk') -ErrorAction SilentlyContinue; "
        "Remove-Item -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\ModNest' "
        "-Recurse -ErrorAction SilentlyContinue"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, creationflags=NO_WINDOW)
    targets = [f'"{install_dir}"']
    if delete_data:
        targets.append(f'"{Path(os.environ.get("APPDATA") or Path.home()) / "ModNest"}"')
    # Programmordner erst löschen, wenn dieses Programm beendet ist
    cmd = "timeout /t 2 /nobreak >nul & " + " & ".join(f"rmdir /s /q {t}" for t in targets)
    subprocess.Popen(["cmd", "/c", cmd], creationflags=NO_WINDOW | subprocess.DETACHED_PROCESS, cwd=str(Path.home()))
    user32.MessageBoxW(None, tr("ModNest wurde deinstalliert."), "ModNest", 0x40)
    return 0
