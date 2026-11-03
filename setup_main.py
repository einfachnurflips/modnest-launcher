"""ModNest-Setup: installiert ModNest ohne Adminrechte nach %LOCALAPPDATA%\\Programs\\ModNest.

Wird von build.py als einzelne .exe gebaut (mit der App als payload.zip darin).

    ModNest-Setup.exe              normale Installation mit Rückfragen
    ModNest-Setup.exe --silent     Update ohne Rückfragen (vom Launcher selbst gestartet)
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

APP = "ModNest"
VERSION = "0.0.0"
try:
    from setup_version import VERSION  # von build.py erzeugt
except ImportError:
    pass

MB_OK, MB_YESNO, MB_ICONINFO, MB_ICONERROR, IDYES = 0x0, 0x4, 0x40, 0x10, 6
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def message(text: str, flags: int = MB_OK | MB_ICONINFO) -> int:
    return ctypes.windll.user32.MessageBoxW(None, text, f"{APP} Setup", flags)


def bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / APP


def _ps(script: str) -> None:
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                   capture_output=True, creationflags=NO_WINDOW, timeout=60)


def _q(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def create_shortcuts(exe: Path) -> None:
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$desk = [Environment]::GetFolderPath('Desktop'); "
        "$start = [Environment]::GetFolderPath('Programs'); "
        "foreach ($p in @(($desk + '\\ModNest.lnk'), ($start + '\\ModNest.lnk'))) { "
        f"$s = $ws.CreateShortcut($p); $s.TargetPath = {_q(str(exe))}; "
        f"$s.WorkingDirectory = {_q(str(exe.parent))}; $s.IconLocation = {_q(str(exe))}; "
        "$s.Description = 'ModNest Minecraft Launcher'; $s.Save() }"
    )
    _ps(script)


def register_uninstall(exe: Path) -> None:
    import winreg
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP}")
    values = {
        "DisplayName": "ModNest Launcher",
        "DisplayVersion": VERSION,
        "Publisher": "ModNest",
        "DisplayIcon": str(exe),
        "InstallLocation": str(exe.parent),
        "UninstallString": f'"{exe}" --uninstall',
    }
    for name, value in values.items():
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
    winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    winreg.CloseKey(key)


def persist_keys() -> None:
    """Eingebaute Schlüssel (nur in der Version für Freunde) in den Datenordner legen."""
    src = bundle_dir() / "default_keys.json"
    if not src.exists():
        return
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except ValueError:
        return
    target = Path(os.environ.get("APPDATA") or Path.home()) / APP
    target.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}
    if data:
        (target / "default_keys.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _remove_old(folder: Path) -> None:
    """Alte Programmdateien entfernen – der Launcher kann nach einem Update noch kurz laufen."""
    for attempt in range(20):
        try:
            for child in folder.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            return
        except OSError:
            time.sleep(0.5)
    raise OSError("Die alte Version ist noch geöffnet. Bitte ModNest schließen und das Setup erneut starten.")


def install(target: Path, silent: bool, system: bool = True) -> Path:
    payload = bundle_dir() / "payload.zip"
    if not payload.exists():
        raise FileNotFoundError("payload.zip fehlt im Setup")
    target.mkdir(parents=True, exist_ok=True)
    _remove_old(target)
    with zipfile.ZipFile(payload) as zf:
        zf.extractall(target)
    exe = target / f"{APP}.exe"
    persist_keys()
    if system:
        create_shortcuts(exe)
        register_uninstall(exe)
    return exe


def main() -> int:
    silent = "--silent" in sys.argv
    system = "--no-system" not in sys.argv          # für Tests: keine Verknüpfungen/Registry
    target = install_dir()
    if "--dir" in sys.argv:
        target = Path(sys.argv[sys.argv.index("--dir") + 1])
    if not silent and message(f"ModNest {VERSION} installieren?\n\nZiel: {target}\n\n"
                              "Es werden keine Adminrechte benötigt. Deine Instanzen und Welten bleiben bei "
                              "einem Update erhalten.", MB_YESNO | MB_ICONINFO) != IDYES:
        return 1
    try:
        exe = install(target, silent, system)
    except Exception as exc:  # noqa: BLE001
        message(f"Installation fehlgeschlagen:\n\n{exc}", MB_OK | MB_ICONERROR)
        return 2
    if "--no-start" in sys.argv:
        return 0
    if silent or message("ModNest ist installiert! 🎉\n\nJetzt starten?", MB_YESNO | MB_ICONINFO) == IDYES:
        subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=subprocess.DETACHED_PROCESS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
