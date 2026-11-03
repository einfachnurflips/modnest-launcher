"""Skins und Umhänge für Microsoft-Konten (Minecraft Services API) plus eine lokale Skin-Bibliothek."""
import json
import re
import shutil
from pathlib import Path

from .config import data_dir
from .i18n import tr
from .sources.base import SourceError, session

API = "https://api.minecraftservices.com/minecraft/profile"


def library_dir() -> Path:
    path = data_dir() / "skins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return library_dir() / "skins.json"


def library() -> list[dict]:
    """[{name, file, variant}] – gespeicherte Skins."""
    try:
        items = json.loads(_index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        items = []
    return [i for i in items if (library_dir() / i.get("file", "")).exists()]


def _save_library(items: list) -> None:
    _index_path().write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def add_to_library(png: Path, name: str, variant: str) -> dict:
    from PySide6.QtGui import QImage
    img = QImage(str(png))
    if img.isNull() or img.width() != 64 or img.height() not in (32, 64):
        raise SourceError(tr("Das ist keine gültige Skin-Datei (PNG mit 64×64 oder 64×32 Pixeln)."))
    items = library()
    base = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:40] or "skin"
    file = f"{base}.png"
    n = 2
    while (library_dir() / file).exists():
        file = f"{base}_{n}.png"
        n += 1
    shutil.copy2(png, library_dir() / file)
    entry = {"name": name, "file": file, "variant": variant}
    items.append(entry)
    _save_library(items)
    return entry


def remove_from_library(entry: dict) -> None:
    (library_dir() / entry["file"]).unlink(missing_ok=True)
    _save_library([i for i in library() if i["file"] != entry["file"]])


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _check(resp, what: str):
    if resp.status_code == 401:
        raise SourceError(tr("Die Anmeldung ist abgelaufen. Bitte das Konto neu anmelden."))
    if resp.status_code == 429:
        raise SourceError(tr("Zu viele Anfragen – bitte kurz warten und erneut versuchen."))
    if not resp.ok:
        raise SourceError(tr("{what} fehlgeschlagen (HTTP {code}).").format(what=what, code=resp.status_code))
    return resp.json() if resp.content else {}


def profile(token: str) -> dict:
    return _check(session.get(API, headers=_headers(token), timeout=20), tr("Profil laden"))


def upload(token: str, png: Path, variant: str) -> dict:
    with open(png, "rb") as fh:
        resp = session.post(f"{API}/skins", headers=_headers(token), timeout=30,
                            data={"variant": variant}, files={"file": ("skin.png", fh, "image/png")})
    return _check(resp, tr("Skin hochladen"))


def set_cape(token: str, cape_id: str | None) -> dict:
    if cape_id:
        resp = session.put(f"{API}/capes/active", headers=_headers(token), json={"capeId": cape_id}, timeout=20)
    else:
        resp = session.delete(f"{API}/capes/active", headers=_headers(token), timeout=20)
    return _check(resp, tr("Umhang ändern"))


def download_texture(url: str, target: Path) -> Path:
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    target.write_bytes(resp.content)
    return target
