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


# --- Erkennen, ob ein Skin schon in der Bibliothek liegt --------------------------
def pixel_key(img) -> str:
    """Prüfsumme über die sichtbaren Pixel – unabhängig davon, wie die PNG-Datei kodiert ist."""
    import hashlib
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    h = hashlib.sha1(f"{img.width()}x{img.height()}".encode())
    for y in range(img.height()):
        row = bytearray()
        for x in range(img.width()):
            argb = img.pixel(x, y)
            row += (argb if argb >> 24 else 0).to_bytes(4, "little")
        h.update(row)
    return h.hexdigest()


def find_in_library(img) -> dict | None:
    """Sucht einen Bibliotheks-Eintrag mit genau diesen Pixeln (merkt sich die Prüfsumme im Index)."""
    from PySide6.QtGui import QImage
    key = pixel_key(img)
    items = library()
    changed = False
    found = None
    for entry in items:
        if "pixels" not in entry:
            other = QImage(str(library_dir() / entry["file"]))
            entry["pixels"] = pixel_key(other) if not other.isNull() else ""
            changed = True
        if entry["pixels"] == key and found is None:
            found = entry
    if changed:
        _save_library(items)
    return found


def keep_skin(data: bytes, name: str, variant: str) -> tuple[dict, bool]:
    """Legt einen Skin (z.B. den aktuell bei Minecraft eingestellten) in der Bibliothek ab, falls er fehlt.
    Gibt (Eintrag, neu_angelegt) zurück."""
    import tempfile
    from PySide6.QtGui import QImage
    img = QImage.fromData(data)
    if img.isNull():
        raise SourceError(tr("Das ist keine gültige Skin-Datei (PNG mit 64×64 oder 64×32 Pixeln)."))
    existing = find_in_library(img)
    if existing:
        return existing, False
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "skin.png"
        path.write_bytes(data)
        entry = add_to_library(path, name, variant)
    items = library()
    for item in items:
        if item["file"] == entry["file"]:
            item["pixels"] = pixel_key(img)
            entry = item
    _save_library(items)
    return entry, True


def player_skin(name: str) -> tuple[bytes, str, str]:
    """Skin eines beliebigen Spielers laden: (PNG-Daten, Variante, richtiger Name)."""
    import base64
    resp = session.get(f"https://api.mojang.com/users/profiles/minecraft/{name.strip()}", timeout=15)
    if resp.status_code in (204, 404):
        raise SourceError(tr("Spieler „{name}“ gibt es nicht.").format(name=name))
    data = _check(resp, tr("Spieler suchen"))
    prof = _check(session.get(f"https://sessionserver.mojang.com/session/minecraft/profile/{data['id']}",
                              timeout=15), tr("Profil laden"))
    textures = {}
    for prop in prof.get("properties", []):
        if prop.get("name") == "textures":
            textures = json.loads(base64.b64decode(prop["value"])).get("textures", {})
    skin = textures.get("SKIN")
    if not skin:
        raise SourceError(tr("„{name}“ benutzt den Standard-Skin.").format(name=data.get("name", name)))
    variant = "slim" if skin.get("metadata", {}).get("model") == "slim" else "classic"
    resp = session.get(skin["url"], timeout=20)
    resp.raise_for_status()
    return resp.content, variant, data.get("name", name)


def rename_in_library(entry: dict, name: str) -> None:
    items = library()
    for item in items:
        if item["file"] == entry["file"]:
            item["name"] = name
    _save_library(items)
