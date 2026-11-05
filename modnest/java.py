"""Java-Verwaltung: installierte Java-Versionen finden und bei Bedarf Eclipse Temurin herunterladen.

Normalerweise lädt Minecraft sein passendes Java selbst (Mojang-Runtime). Eigenes Java braucht man
nur in Sonderfällen – z.B. für bestimmte Modpacks oder zum Testen.
"""
import hashlib
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .config import data_dir, minecraft_dir
from .i18n import tr
from .sources.base import download, session

ADOPTIUM = "https://api.adoptium.net/v3"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class JavaInstall:
    path: Path            # javaw.exe
    version: str
    source: str

    @property
    def major(self) -> int:
        m = re.match(r"(?:1\.)?(\d+)", self.version)
        return int(m.group(1)) if m else 0


def java_dir() -> Path:
    path = data_dir() / "java"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _version(javaw: Path) -> str:
    java = javaw.with_name("java.exe") if javaw.with_name("java.exe").exists() else javaw
    try:
        out = subprocess.run([str(java), "-version"], capture_output=True, text=True, timeout=15,
                             creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r'version "([^"]+)"', out.stderr + out.stdout)
    return m.group(1) if m else ""


def _candidates() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for exe in (minecraft_dir() / "runtime").rglob("javaw.exe") if (minecraft_dir() / "runtime").exists() else []:
        found.append((exe, tr("Minecraft (automatisch)")))
    for exe in java_dir().glob("*/bin/javaw.exe"):
        found.append((exe, "ModNest"))
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / "javaw.exe").exists():
        found.append((Path(home) / "bin" / "javaw.exe", "JAVA_HOME"))
    for base in {os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")} - {None}:
        for vendor in ("Java", "Eclipse Adoptium", "Microsoft", "Zulu", "BellSoft", "Amazon Corretto", "Eclipse Foundation"):
            for exe in (Path(base) / vendor).glob("*/bin/javaw.exe"):
                found.append((exe, vendor))
    exe = shutil.which("javaw")
    if exe:
        found.append((Path(exe), "PATH"))
    unique, seen = [], set()
    for exe, source in found:
        key = str(exe.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append((exe, source))
    return unique


def find_all() -> list[JavaInstall]:
    result = []
    for exe, source in _candidates():
        version = _version(exe)
        if version:
            result.append(JavaInstall(exe, version, source))
    return sorted(result, key=lambda j: (-j.major, j.source))


def recommended_major(mc_version: str) -> int:
    """Java-Version, die eine Minecraft-Version braucht."""
    parts = [int(x) for x in re.findall(r"\d+", mc_version)[:3]] or [0]
    if parts[0] >= 24:            # neue Jahresversionen (z.B. 26.1)
        return 25
    minor = parts[1] if len(parts) > 1 else 0
    patch = parts[2] if len(parts) > 2 else 0
    if minor >= 21 or (minor == 20 and patch >= 5):
        return 21
    if minor >= 18:
        return 17
    if minor == 17:
        return 16
    return 8


def available_features() -> list[int]:
    data = session.get(f"{ADOPTIUM}/info/available_releases", timeout=20).json()
    return sorted(set(data.get("available_lts_releases", [])) | {data.get("most_recent_feature_release", 0)} - {0})


def install_temurin(feature: int, progress=lambda *a: None) -> JavaInstall:
    """Lädt Eclipse Temurin (JRE) herunter und entpackt es nach %APPDATA%\\ModNest\\java."""
    assets = session.get(f"{ADOPTIUM}/assets/latest/{feature}/hotspot", timeout=20, params={
        "architecture": "x64", "image_type": "jre", "os": "windows", "vendor": "eclipse"}).json()
    if not assets:
        assets = session.get(f"{ADOPTIUM}/assets/latest/{feature}/hotspot", timeout=20, params={
            "architecture": "x64", "image_type": "jdk", "os": "windows", "vendor": "eclipse"}).json()
    pkg = next((a["binary"]["package"] for a in assets if a["binary"]["package"]["name"].endswith(".zip")), None)
    if pkg is None:
        raise OSError(tr("Für Java {v} gibt es keinen Download.").format(v=feature))
    target_dir = java_dir() / f"temurin-{feature}"
    archive = java_dir() / pkg["name"]
    label = tr("Lade Java {v} …").format(v=feature)
    download(pkg["link"], archive, lambda done, total: progress(label, done * 100 // total, 100))
    if pkg.get("checksum"):
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest.lower() != pkg["checksum"].lower():
            archive.unlink(missing_ok=True)
            raise OSError(tr("Die heruntergeladene Datei ist beschädigt (Prüfsumme falsch)."))
    progress(tr("Entpacke Java {v} …").format(v=feature), 0, 0)
    tmp = java_dir() / f".tmp-{feature}"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(tmp)
    archive.unlink(missing_ok=True)
    inner = next((p for p in tmp.iterdir() if (p / "bin" / "javaw.exe").exists()), tmp)
    shutil.rmtree(target_dir, ignore_errors=True)
    shutil.move(str(inner), str(target_dir))
    shutil.rmtree(tmp, ignore_errors=True)
    exe = target_dir / "bin" / "javaw.exe"
    return JavaInstall(exe, _version(exe), "ModNest")
