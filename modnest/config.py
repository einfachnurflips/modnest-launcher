"""Pfade und Launcher-Einstellungen."""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "ModNest"
APP_VERSION = "0.2.0"
USER_AGENT = f"ModNest-Launcher/{APP_VERSION}"


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def instances_dir() -> Path:
    path = data_dir() / "instances"
    path.mkdir(parents=True, exist_ok=True)
    return path


def minecraft_dir() -> Path:
    """Gemeinsamer Ordner für Versionen, Libraries, Assets und Java-Runtimes."""
    path = data_dir() / "minecraft"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    username: str = "Steve"
    ram_mb: int = 4096
    java_path: str = ""
    curseforge_api_key: str = ""
    ms_client_id: str = ""          # Azure-App für den Microsoft-Login
    last_instance: str = ""
    theme: str = "dark"             # dark | light | system
    language: str = "de"            # de | en
    backup_dir: str = ""            # leer = %APPDATA%\ModNest\backups
    backup_worlds: bool = True      # Welten beim Beenden des Spiels sichern
    backup_screenshots: bool = True # Screenshots automatisch sichern
    backup_keep: int = 5            # Anzahl Welt-Backups pro Welt
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        path = data_dir() / "settings.json"
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        path = data_dir() / "settings.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
