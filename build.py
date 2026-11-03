"""Baut ModNest als Windows-Programm plus Setup.

    .venv\\Scripts\\python build.py            → dist\\ModNest-Setup-<Version>.exe  (mit deinen Schlüsseln, für Freunde)
    .venv\\Scripts\\python build.py --public   → dist\\public\\ModNest-Setup-<Version>.exe  (ohne Schlüssel, für GitHub)

Die Schlüssel kommen aus modnest/default_keys.json (wird nie hochgeladen). Das Setup legt sie beim
Installieren in %APPDATA%\\ModNest ab, damit sie auch spätere Updates überstehen.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"


def run(*args: str) -> None:
    print(">", " ".join(args))
    subprocess.run(args, check=True, cwd=ROOT)


def main() -> None:
    public = "--public" in sys.argv
    sys.path.insert(0, str(ROOT))
    from modnest.config import APP_VERSION

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        run(sys.executable, "-m", "pip", "install", "pyinstaller")

    # Icon erzeugen
    from PySide6.QtWidgets import QApplication
    from modnest.ui.icons import save_ico
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 – für QPixmap nötig
    ico = BUILD / "ModNest.ico"
    BUILD.mkdir(exist_ok=True)
    save_ico(ico)

    # 1) Launcher als Ordner-Programm (startet schneller als eine einzelne Datei)
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "ModNest",
        "--icon", str(ico), "--distpath", str(BUILD / "app"), "--workpath", str(BUILD / "work-app"),
        "--specpath", str(BUILD), "--collect-data", "minecraft_launcher_lib",
        "--exclude-module", "tkinter", "--exclude-module", "modnest.default_keys",
        str(ROOT / "main.py"))
    app_dir = BUILD / "app" / "ModNest"
    leaked = list(app_dir.rglob("default_keys.json"))
    if leaked:
        raise SystemExit(f"Schlüsseldatei im Programm gefunden – Abbruch: {leaked}")

    # 2) Programm in payload.zip packen
    payload = BUILD / "payload.zip"
    payload.unlink(missing_ok=True)
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in app_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(app_dir).as_posix())
    (BUILD / "setup_version.py").write_text(f'VERSION = "{APP_VERSION}"\n', encoding="utf-8")

    # 3) Setup als einzelne .exe
    out = DIST / "public" if public else DIST
    name = f"ModNest-Setup-{APP_VERSION}"
    data = [f"{payload};."]
    keys = ROOT / "modnest" / "default_keys.json"
    if not public and keys.exists():
        data.append(f"{keys};.")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--name", name,
           "--icon", str(ico), "--distpath", str(out), "--workpath", str(BUILD / "work-setup"),
           "--specpath", str(BUILD), "--paths", str(BUILD)]
    for d in data:
        cmd += ["--add-data", d]
    run(*cmd, str(ROOT / "setup_main.py"))
    setup = out / f"{name}.exe"
    print(f"\nFertig: {setup}  ({setup.stat().st_size / 1_048_576:.0f} MB)"
          f"{'  – OHNE Schlüssel' if public or not keys.exists() else '  – mit deinen Schlüsseln (nicht hochladen!)'}")


if __name__ == "__main__":
    main()
