"""Eingebaute Schlüssel für weitergegebene Versionen (z.B. die Setup-.exe für Freunde).

Die Werte stehen NICHT im Quellcode, sondern in einer default_keys.json:
  • modnest/default_keys.json  – nur lokal, per .gitignore von GitHub ausgeschlossen
  • %APPDATA%/ModNest/default_keys.json – legt das Setup an, damit die Schlüssel auch nach
    Updates (die ohne Schlüssel veröffentlicht werden) erhalten bleiben.
Fehlt beides, gelten nur die Werte aus den Einstellungen.
"""
import json
import os
import sys
from pathlib import Path

FIELDS = ("curseforge_api_key", "ms_client_id", "discord_client_id")


def candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    bundle = Path(getattr(sys, "_MEIPASS", here.parent))
    appdata = Path(os.environ.get("APPDATA") or Path.home()) / "ModNest"
    return [bundle / "modnest" / "default_keys.json", here / "default_keys.json", appdata / "default_keys.json"]


def _load() -> dict:
    keys: dict = {}
    for path in candidates():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for k in FIELDS:
            value = str(data.get(k) or "").strip()
            if value and not keys.get(k):
                keys[k] = value
    return keys


def persist(keys: dict) -> None:
    """Speichert Schlüssel im Datenordner (vom Setup aufgerufen)."""
    target = Path(os.environ.get("APPDATA") or Path.home()) / "ModNest"
    target.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in keys.items() if k in FIELDS and v}
    if data:
        (target / "default_keys.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


DEFAULT_KEYS = _load()
