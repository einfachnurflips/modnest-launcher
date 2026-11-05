"""BlueMap-Karten von Servern: Adresse merken, prüfen und in einem eigenen App-Fenster öffnen.

BlueMap (Server-Plugin/Mod) stellt eine 3D-Webkarte bereit, meist unter http://<server>:8100/.
ModNest öffnet sie im App-Modus von Microsoft Edge (Fenster ohne Adress- und Tableiste) –
Edge ist auf jedem Windows 10/11 vorhanden. Ohne Edge wird der Standardbrowser genutzt.
"""
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .config import data_dir
from .sources.base import session

DEFAULT_PORT = 8100


def _key(address: str) -> str:
    return address.strip().lower()


def saved_url(settings, address: str) -> str:
    return (settings.extra.get("maps") or {}).get(_key(address), "")


def save_url(settings, address: str, url: str) -> None:
    maps = dict(settings.extra.get("maps") or {})
    if url:
        maps[_key(address)] = url
    else:
        maps.pop(_key(address), None)
    settings.extra["maps"] = maps
    settings.save()


def guess_url(address: str) -> str:
    host = address.strip()
    if host.startswith("["):                      # IPv6 [::1]:25565
        host = host.split("]")[0] + "]"
    elif host.count(":") == 1:
        host = host.split(":")[0]
    return f"http://{host}:{DEFAULT_PORT}/"


def normalize(url: str) -> str:
    url = url.strip()
    if url and "://" not in url:
        url = "http://" + url
    if url and not url.endswith("/") and not urlparse(url).path.rsplit("/", 1)[-1].count("."):
        url += "/"
    return url


def check(url: str) -> list[str]:
    """Prüft, ob unter der Adresse eine BlueMap läuft. Gibt die Kartennamen zurück (Fehler → Exception)."""
    resp = session.get(url.rstrip("/") + "/settings.json", timeout=8)
    resp.raise_for_status()
    data = resp.json()
    if "maps" not in data and "mapDataRoot" not in data:
        raise ValueError("Keine BlueMap")
    return [str(m) for m in data.get("maps", [])]


def _edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if path.exists():
                return str(path)
    return None


def open_window(url: str) -> bool:
    """Öffnet die Karte als eigenes Fenster. False = kein Edge gefunden (dann Browser nutzen)."""
    edge = _edge()
    if not edge:
        return False
    # Eigenes Profil, damit das Fenster unabhängig von offenen Browser-Fenstern startet
    profile = data_dir() / "map-window"
    subprocess.Popen([edge, f"--app={url}", "--window-size=1400,900", f"--user-data-dir={profile}",
                      "--no-first-run", "--no-default-browser-check"],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True
