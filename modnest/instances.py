"""Instanzen: ein Ordner pro Modpack mit instance.json, mods/, resourcepacks/, shaderpacks/ usw.

Für jede Inhaltsart (Mods, Texturepacks, Shader) speichert instance.json die Kategorien
(in Reihenfolge) und alle Einträge in der vom Nutzer festgelegten Reihenfolge.
"""
import json
import re
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .config import instances_dir
from .trash import move_to_trash

FALLBACK_CATEGORY = "Unkategorisiert"
DISABLED = ".disabled"

KINDS = {
    "mods": {"label": "Mods", "singular": "Mod", "folder": "mods", "exts": (".jar",), "dirs": False},
    "resourcepacks": {"label": "Texturepacks", "singular": "Texturepack", "folder": "resourcepacks",
                      "exts": (".zip",), "dirs": True},
    "shaderpacks": {"label": "Shader", "singular": "Shader", "folder": "shaderpacks",
                    "exts": (".zip",), "dirs": True},
}

DEFAULT_CATEGORIES = {
    "mods": [
        {"name": "Performance", "color": "#4ade80"},
        {"name": "Grafik & Optik", "color": "#c084fc"},
        {"name": "Gameplay & Inhalte", "color": "#fb923c"},
        {"name": "Utility & QoL", "color": "#38bdf8"},
        {"name": "Bibliotheken", "color": "#94a3b8"},
        {"name": FALLBACK_CATEGORY, "color": "#9ca3af"},
    ],
    "resourcepacks": [
        {"name": "Vanilla+", "color": "#4ade80"},
        {"name": "Realistisch", "color": "#38bdf8"},
        {"name": "Stilisiert", "color": "#c084fc"},
        {"name": "PvP", "color": "#f87171"},
        {"name": FALLBACK_CATEGORY, "color": "#9ca3af"},
    ],
    "shaderpacks": [
        {"name": "Leicht & schnell", "color": "#4ade80"},
        {"name": "Realistisch", "color": "#38bdf8"},
        {"name": "Fantasy & Stilisiert", "color": "#c084fc"},
        {"name": FALLBACK_CATEGORY, "color": "#9ca3af"},
    ],
}

LOADERS = {
    "vanilla": "Vanilla",
    "fabric": "Fabric",
    "quilt": "Quilt",
    "forge": "Forge",
    "neoforge": "NeoForge",
}


@dataclass
class Mod:
    """Ein installierter Inhalt (Mod, Texturepack oder Shader)."""
    file: str                      # Datei-/Ordnername ohne ".disabled"
    name: str = ""
    source: str = "local"          # modrinth | curseforge | local
    project_id: str = ""
    version_id: str = ""
    version_name: str = ""
    category: str = FALLBACK_CATEGORY
    enabled: bool = True
    icon_url: str = ""
    url: str = ""
    description: str = ""
    pinned: bool = False           # Version bewusst gewählt (nicht automatisch aktualisieren)
    note: str = ""                 # eigene Notiz, z.B. „nicht updaten, crasht mit X“

    @classmethod
    def from_dict(cls, raw: dict) -> "Mod":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in names})

    @property
    def disk_name(self) -> str:
        return self.file if self.enabled else self.file + DISABLED


class ContentSet:
    """Alle Einträge einer Inhaltsart einer Instanz, samt Kategorien."""

    def __init__(self, kind: str, instance_path: Path):
        self.kind = kind
        self.instance_path = instance_path
        self.categories: list[dict] = [dict(c) for c in DEFAULT_CATEGORIES[kind]]
        self.items: list[Mod] = []

    @property
    def info(self) -> dict:
        return KINDS[self.kind]

    @property
    def folder(self) -> Path:
        path = self.instance_path / self.info["folder"]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load_raw(self, categories: list | None, items: list | None) -> None:
        if categories:
            self.categories = categories
        self.items = [Mod.from_dict(m) for m in items or []]
        if FALLBACK_CATEGORY not in self.category_names():
            self.categories.append({"name": FALLBACK_CATEGORY, "color": "#9ca3af"})

    def _matches(self, path: Path) -> tuple[str, bool] | None:
        """(Name ohne .disabled, aktiviert) für passende Dateien/Ordner, sonst None."""
        name = path.name
        enabled = not name.endswith(DISABLED)
        base = name if enabled else name[: -len(DISABLED)]
        if path.is_dir():
            return (base, enabled) if self.info["dirs"] and not base.startswith(".") else None
        if base.lower().endswith(self.info["exts"]):
            return base, enabled
        return None

    def sync_with_disk(self) -> None:
        """Gleicht die Liste mit dem Ordner ab (manuell hinzugefügte/gelöschte Dateien)."""
        on_disk: dict[str, bool] = {}
        for p in self.folder.iterdir():
            hit = self._matches(p)
            if hit:
                on_disk[hit[0]] = hit[1]
        kept, known = [], set()
        for item in self.items:
            if item.file in on_disk:
                item.enabled = on_disk[item.file]
                kept.append(item)
                known.add(item.file)
        for file, enabled in sorted(on_disk.items()):
            if file not in known:
                kept.append(Mod(file=file, name=Path(file).stem, enabled=enabled))
        valid = set(self.category_names())
        for item in kept:
            if item.category not in valid:
                item.category = FALLBACK_CATEGORY
        self.items = kept

    # --- Kategorien --------------------------------------------------------
    def category_names(self) -> list[str]:
        return [c["name"] for c in self.categories]

    def category_color(self, name: str) -> str:
        for c in self.categories:
            if c["name"] == name:
                return c.get("color", "#9ca3af")
        return "#9ca3af"

    def add_category(self, name: str, color: str = "#64748b") -> None:
        if name and name not in self.category_names():
            self.categories.insert(max(len(self.categories) - 1, 0), {"name": name, "color": color})

    def rename_category(self, old: str, new: str) -> None:
        if not new or new in self.category_names() or old == FALLBACK_CATEGORY:
            return
        for c in self.categories:
            if c["name"] == old:
                c["name"] = new
        for m in self.items:
            if m.category == old:
                m.category = new

    def set_category_color(self, name: str, color: str) -> None:
        for c in self.categories:
            if c["name"] == name:
                c["color"] = color

    def delete_category(self, name: str) -> None:
        if name == FALLBACK_CATEGORY:
            return
        self.categories = [c for c in self.categories if c["name"] != name]
        for m in self.items:
            if m.category == name:
                m.category = FALLBACK_CATEGORY

    def apply_layout(self, category_order: list[str], item_order: list[tuple[str, str]]) -> None:
        """Übernimmt die Anordnung aus der Oberfläche (Drag & Drop)."""
        by_name = {c["name"]: c for c in self.categories}
        self.categories = [by_name[n] for n in category_order if n in by_name] + [
            c for c in self.categories if c["name"] not in category_order
        ]
        by_file = {m.file: m for m in self.items}
        ordered = []
        for file, category in item_order:
            item = by_file.pop(file, None)
            if item:
                item.category = category
                ordered.append(item)
        self.items = ordered + list(by_file.values())

    # --- Einträge ----------------------------------------------------------
    def find_project(self, source: str, project_id: str) -> Mod | None:
        for m in self.items:
            if m.source == source and m.project_id == project_id:
                return m
        return None

    def find_file(self, file: str) -> Mod | None:
        return next((m for m in self.items if m.file == file), None)

    def add(self, item: Mod) -> None:
        """Fügt einen Eintrag hinzu; ersetzt eine andere Version desselben Projekts an gleicher Stelle."""
        old = self.find_project(item.source, item.project_id) if item.project_id else None
        if old is None:
            old = self.find_file(item.file)
        if old is not None:
            if old.disk_name != item.file:
                _delete(self.folder / old.disk_name)
            item.category = old.category
            item.note = item.note or old.note
            if not old.enabled:
                # Deaktivierten Zustand beibehalten
                (self.folder / item.file).rename(self.folder / (item.file + DISABLED))
                item.enabled = False
            self.items[self.items.index(old)] = item
        else:
            self.items.append(item)

    def remove(self, file: str) -> None:
        for m in list(self.items):
            if m.file == file:
                move_to_trash(self.folder / m.disk_name)
                self.items.remove(m)

    def set_enabled(self, file: str, enabled: bool) -> None:
        for m in self.items:
            if m.file == file and m.enabled != enabled:
                src = self.folder / m.disk_name
                m.enabled = enabled
                if src.exists():
                    src.rename(self.folder / m.disk_name)

    def to_raw(self) -> dict:
        return {"categories": self.categories, "items": [asdict(m) for m in self.items]}


def _delete(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


class Instance:
    def __init__(self, path: Path):
        self.path = path
        self.name = path.name
        self.mc_version = ""
        self.loader = "fabric"
        self.loader_version = ""
        self.version_id = ""       # installierte Versions-ID (z.B. fabric-loader-0.16-1.21.1)
        self.icon = ""             # Dateiname eines eigenen Icons im Instanz-Ordner
        self.playtime = 0          # gespielte Sekunden
        self.last_played = 0.0     # Unix-Zeit des letzten Starts
        self.ram_mb = 0            # 0 = globale Einstellung
        self.java_path = ""        # leer = globale Einstellung
        self.jvm_args = ""         # zusätzliche Java-Argumente
        self.pack: dict = {}       # Herkunft, falls aus einem fertigen Modpack installiert
        self.profiles: dict = {}   # Mod-Profile: Name → {Art: [aktivierte Dateien]}
        self.group = ""            # Ordner in der Seitenleiste
        self.account_id = ""       # eigenes Konto für diese Instanz (leer = aktives Konto)
        self.content = {kind: ContentSet(kind, path) for kind in KINDS}

    # Kurzformen für die Mods (häufigster Fall)
    @property
    def mods(self) -> list[Mod]:
        return self.content["mods"].items

    @property
    def json_path(self) -> Path:
        return self.path / "instance.json"

    @property
    def icon_path(self) -> Path | None:
        if self.icon and (self.path / self.icon).exists():
            return self.path / self.icon
        return None

    @classmethod
    def load(cls, path: Path) -> "Instance":
        inst = cls(path)
        raw = json.loads(inst.json_path.read_text(encoding="utf-8"))
        inst.name = raw.get("name", path.name)
        inst.mc_version = raw.get("mc_version", "")
        inst.loader = raw.get("loader", "fabric")
        inst.loader_version = raw.get("loader_version", "")
        inst.version_id = raw.get("version_id", "")
        inst.icon = raw.get("icon", "")
        inst.playtime = int(raw.get("playtime", 0))
        inst.last_played = float(raw.get("last_played", 0))
        inst.ram_mb = int(raw.get("ram_mb", 0) or 0)
        inst.java_path = raw.get("java_path", "")
        inst.jvm_args = raw.get("jvm_args", "")
        inst.pack = raw.get("pack") or {}
        inst.profiles = raw.get("profiles") or {}
        inst.group = raw.get("group", "")
        inst.account_id = raw.get("account_id", "")
        # Mods stehen aus Kompatibilitätsgründen direkt auf oberster Ebene
        inst.content["mods"].load_raw(raw.get("categories"), raw.get("mods"))
        for kind in ("resourcepacks", "shaderpacks"):
            part = raw.get(kind) or {}
            inst.content[kind].load_raw(part.get("categories"), part.get("items"))
        inst.sync_with_disk()
        return inst

    def sync_with_disk(self) -> None:
        for cs in self.content.values():
            cs.sync_with_disk()

    def save(self) -> None:
        mods = self.content["mods"].to_raw()
        data = {
            "name": self.name,
            "mc_version": self.mc_version,
            "loader": self.loader,
            "loader_version": self.loader_version,
            "version_id": self.version_id,
            "icon": self.icon,
            "playtime": self.playtime,
            "last_played": self.last_played,
            "ram_mb": self.ram_mb,
            "java_path": self.java_path,
            "jvm_args": self.jvm_args,
            "pack": self.pack,
            "profiles": self.profiles,
            "group": self.group,
            "account_id": self.account_id,
            "categories": mods["categories"],
            "mods": mods["items"],
            "resourcepacks": self.content["resourcepacks"].to_raw(),
            "shaderpacks": self.content["shaderpacks"].to_raw(),
        }
        tmp = self.json_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.json_path)

    # --- Mod-Profile ------------------------------------------------------------
    def save_profile(self, name: str) -> None:
        """Merkt sich, welche Mods, Texturepacks und Shader gerade aktiviert sind."""
        self.profiles[name] = {kind: {"on": [m.file for m in cs.items if m.enabled],
                                      "off": [m.file for m in cs.items if not m.enabled]}
                               for kind, cs in self.content.items()}
        self.save()

    def apply_profile(self, name: str) -> int:
        """Schaltet alles so, wie im Profil gespeichert. Gibt die Zahl der Änderungen zurück."""
        profile = self.profiles.get(name)
        if profile is None:
            return 0
        changed = 0
        for kind, cs in self.content.items():
            if kind not in profile:
                continue
            on, off = set(profile[kind].get("on", [])), set(profile[kind].get("off", []))
            for m in cs.items:
                if m.file not in on and m.file not in off:
                    continue   # nach dem Speichern neu installiert – Zustand beibehalten
                enabled = m.file in on
                if m.enabled != enabled:
                    cs.set_enabled(m.file, enabled)
                    changed += 1
        self.save()
        return changed

    def delete_profile(self, name: str) -> None:
        self.profiles.pop(name, None)
        self.save()

    def write_resourcepack_order(self) -> None:
        """Überträgt aktivierte Texturepacks in ihrer Reihenfolge in options.txt.

        Oben in der Liste = höchste Priorität (in Minecraft steht die höchste Priorität am Ende).
        """
        cs = self.content["resourcepacks"]
        ours = [f"file/{m.file}" for m in cs.items if m.enabled]
        options = self.path / "options.txt"
        lines = options.read_text(encoding="utf-8", errors="replace").splitlines() if options.exists() else []
        existing: list[str] = ["vanilla"]
        for line in lines:
            if line.startswith("resourcePacks:"):
                try:
                    existing = json.loads(line.split(":", 1)[1])
                except ValueError:
                    pass
        # Packs von Mods (z.B. "fabric") behalten, eigene Packs neu ordnen
        new = [e for e in existing if not e.startswith("file/")] + list(reversed(ours))
        if "vanilla" not in new:
            new.insert(0, "vanilla")
        entry = "resourcePacks:" + json.dumps(new)
        lines = [l for l in lines if not l.startswith("resourcePacks:") and not l.startswith("incompatibleResourcePacks:")]
        lines.append(entry)
        options.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9 _.-]", "", name).strip() or "Instanz"
    return slug[:60]


def list_instances() -> list[Instance]:
    result = []
    for p in sorted(instances_dir().iterdir()):
        if (p / "instance.json").exists():
            try:
                result.append(Instance.load(p))
            except (OSError, ValueError):
                continue
    return result


def _free_path(name: str) -> Path:
    base = _slug(name)
    path = instances_dir() / base
    n = 2
    while path.exists():
        path = instances_dir() / f"{base} ({n})"
        n += 1
    return path


DEFAULT_FILES = ("options.txt", "optionsof.txt", "optionsshaders.txt", "servers.dat")


def defaults_dir() -> Path:
    from .config import data_dir
    return data_dir() / "defaults"


def has_defaults() -> bool:
    return (defaults_dir() / "options.txt").exists()


def save_defaults(inst: "Instance") -> list[str]:
    """Merkt sich Tastenbelegung, Grafik- und Spracheinstellungen dieser Instanz für neue Instanzen."""
    target = defaults_dir()
    target.mkdir(parents=True, exist_ok=True)
    saved = []
    for name in DEFAULT_FILES:
        if (inst.path / name).is_file():
            shutil.copy2(inst.path / name, target / name)
            saved.append(name)
    return saved


def clear_defaults() -> None:
    shutil.rmtree(defaults_dir(), ignore_errors=True)


def create_instance(name: str, mc_version: str, loader: str, use_defaults: bool = True) -> Instance:
    path = _free_path(name)
    path.mkdir(parents=True)
    inst = Instance(path)
    inst.name = name
    inst.mc_version = mc_version
    inst.loader = loader
    for cs in inst.content.values():
        cs.folder  # legt die Ordner an
    if use_defaults and defaults_dir().is_dir():
        for file in DEFAULT_FILES:
            src = defaults_dir() / file
            if src.is_file():
                shutil.copy2(src, path / file)
    inst.save()
    return inst


def delete_instance(inst: Instance) -> None:
    """Verschiebt die Instanz in den Papierkorb (wiederherstellbar)."""
    move_to_trash(inst.path)


# Ordner, die beim Kopieren nie mitgenommen werden (Laufzeitdaten)
_SKIP_ON_COPY = {"logs", "crash-reports", ".fabric", "launcher-log.txt", "debug"}


def duplicate_instance(inst: Instance, new_name: str, include_worlds: bool, include_screenshots: bool = False) -> Instance:
    """Kopiert eine Instanz inklusive Mods, Packs, Kategorien und Configs."""
    skip = set(_SKIP_ON_COPY)
    if not include_worlds:
        skip.add("saves")
    if not include_screenshots:
        skip.add("screenshots")
    path = _free_path(new_name)
    shutil.copytree(inst.path, path, ignore=lambda d, names: [n for n in names if Path(d) == inst.path and n in skip])
    copy = Instance.load(path)
    copy.name = new_name
    copy.playtime = 0
    copy.last_played = 0
    copy.save()
    return copy
