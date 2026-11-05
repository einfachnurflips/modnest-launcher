"""Pfade und Launcher-Einstellungen."""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "ModNest"
APP_VERSION = "0.4.0"
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
    backup_before_updates: bool = True  # Instanz (ohne Welten) vor Mod-/Modpack-Updates sichern
    minimize_on_launch: bool = False  # Launcher beim Spielen minimieren
    discord_rpc: bool = True        # „Spielt …“ in Discord anzeigen
    discord_client_id: str = ""     # Discord-Anwendungs-ID (leer = aus)
    tray_icon: bool = True          # Symbol im Infobereich der Taskleiste
    close_to_tray: bool = False     # Schließen-Knopf versteckt ModNest nur im Tray
    extra: dict = field(default_factory=dict)

    KEY_FIELDS = ("curseforge_api_key", "ms_client_id", "discord_client_id")

    def __post_init__(self):
        """Leere Schlüssel mit den eingebauten Werten füllen (siehe keys.py) – gespeichert werden sie nie."""
        from .keys import DEFAULT_KEYS
        self._defaults = {}
        for name in self.KEY_FIELDS:
            default = DEFAULT_KEYS.get(name, "")
            if default and not getattr(self, name).strip():
                setattr(self, name, default)
                self._defaults[name] = default

    def builtin(self, name: str) -> str:
        from .keys import DEFAULT_KEYS
        return DEFAULT_KEYS.get(name, "")

    def is_builtin(self, name: str) -> bool:
        return bool(self.builtin(name)) and getattr(self, name) == self.builtin(name)

    def set_key(self, name: str, value: str) -> None:
        """Leer = eingebauten Wert verwenden."""
        value = value.strip()
        setattr(self, name, value or self.builtin(name))

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
        data = asdict(self)
        for name in self.KEY_FIELDS:
            if self.builtin(name) and data[name] == self.builtin(name):
                data[name] = ""     # eingebaute Schlüssel nicht in settings.json schreiben
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
