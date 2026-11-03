"""Desktop-Verknüpfungen, die eine Instanz direkt starten."""
import re
import subprocess
import sys
from pathlib import Path

from .config import data_dir


def launch_command() -> tuple[str, str]:
    """(Programm, Argumente) zum Starten von ModNest – als .exe oder als Python-Skript."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent / "main.py"
    return str(pythonw if pythonw.exists() else exe), f'"{main}"'


def desktop_dir() -> Path:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True, timeout=20,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        path = Path(out.stdout.strip())
        if path.is_dir():
            return path
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def create_instance_shortcut(instance, icon_ico: Path | None) -> Path:
    """Legt auf dem Desktop eine Verknüpfung an, die diese Instanz sofort startet."""
    program, base_args = launch_command()
    args = f'{base_args} --play "{instance.path.name}"'.strip()
    safe = re.sub(r'[<>:"/\\|?*]', "_", instance.name)
    link = desktop_dir() / f"{safe}.lnk"
    icon = str(icon_ico) if icon_ico and icon_ico.exists() else program
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps_quote(str(link)) + "); "
        "$s.TargetPath = " + _ps_quote(program) + "; "
        "$s.Arguments = " + _ps_quote(args) + "; "
        "$s.WorkingDirectory = " + _ps_quote(str(Path(program).parent if getattr(sys, "frozen", False)
                                                    else Path(__file__).resolve().parent.parent)) + "; "
        "$s.IconLocation = " + _ps_quote(icon) + "; "
        "$s.Description = " + _ps_quote(f"{instance.name} mit ModNest starten") + "; "
        "$s.Save()"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                            timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0 or not link.exists():
        raise OSError(result.stderr.strip() or "Verknüpfung konnte nicht erstellt werden")
    return link


def icon_cache_dir() -> Path:
    path = data_dir() / "shortcut-icons"
    path.mkdir(parents=True, exist_ok=True)
    return path
