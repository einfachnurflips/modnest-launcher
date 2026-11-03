"""Kompatibilitäts-Check: findet typische Probleme, bevor Minecraft abstürzt.

Geprüft wird anhand der Metadaten in den Mod-Dateien (fabric.mod.json, quilt.mod.json,
META-INF/mods.toml, META-INF/neoforge.mods.toml):
  • Mods für den falschen Loader (z.B. Forge-Mod in einer Fabric-Instanz)
  • dieselbe Mod doppelt installiert
  • fehlende Pflicht-Abhängigkeiten
  • bekannte Unverträglichkeiten (z.B. Sodium + OptiFine)
"""
import io
import json
import re
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import tr
from .instances import Instance

# Abhängigkeiten, die vom Spiel bzw. Loader selbst kommen
BUILTIN = {"minecraft", "java", "fabricloader", "fabric-loader", "quilt_loader", "quilt_base", "forge", "neoforge",
           "mixinextras", "fml", "javafml", "lowcodefml"}

# (Mod-IDs A, Mod-IDs B, Erklärung)
CONFLICTS = [
    ({"sodium", "embeddium", "rubidium"}, {"optifine", "optifabric"},
     tr("Sodium/Embeddium und OptiFine ersetzen beide die Grafik-Engine und stürzen zusammen ab. "
        "Nimm Sodium + Iris statt OptiFine.")),
    ({"sodium"}, {"embeddium", "rubidium"}, tr("Sodium und Embeddium/Rubidium sind dieselbe Mod in zwei Varianten.")),
    ({"iris"}, {"oculus"}, tr("Iris und Oculus sind dieselbe Shader-Mod in zwei Varianten.")),
    ({"iris", "oculus"}, {"optifine", "optifabric"}, tr("Iris/Oculus und OptiFine können nicht zusammen laufen.")),
    ({"lithium"}, {"canary", "radium"}, tr("Lithium und Canary/Radium sind dieselbe Mod in zwei Varianten.")),
    ({"starlight"}, {"phosphor", "moonrise"}, tr("Starlight, Phosphor und Moonrise ändern alle das Licht-System.")),
    ({"c2me"}, {"optifine", "optifabric"}, tr("C2ME und OptiFine vertragen sich nicht.")),
]


@dataclass
class ModMeta:
    file: str
    enabled: bool
    loaders: set = field(default_factory=set)       # fabric / quilt / forge / neoforge
    ids: set = field(default_factory=set)           # eigene IDs inkl. provides und eingebettete Jars
    main_id: str = ""
    name: str = ""
    depends: set = field(default_factory=set)


@dataclass
class Issue:
    severity: str        # "error" | "warning"
    title: str
    detail: str
    files: list = field(default_factory=list)
    kind: str = ""       # loader | duplicate | missing | conflict
    deps: list = field(default_factory=list)


def _fabric_meta(data: bytes, meta: ModMeta, top: bool, loader: str) -> list:
    try:
        info = json.loads(data.decode("utf-8", errors="replace"), strict=False)
    except ValueError:
        return []
    if loader == "quilt":
        q = info.get("quilt_loader", {})
        mod_id = q.get("id", "")
        provides = [p if isinstance(p, str) else p.get("id", "") for p in q.get("provides", [])]
        deps = [d if isinstance(d, str) else d.get("id", "") for d in q.get("depends", [])
                if isinstance(d, str) or not d.get("optional")]
        jars = [j if isinstance(j, str) else j.get("file", "") for j in q.get("jars", [])]
        name = (q.get("metadata") or {}).get("name", "")
    else:
        mod_id = info.get("id", "")
        provides = info.get("provides", [])
        deps = list((info.get("depends") or {}).keys())
        jars = [j.get("file", "") for j in info.get("jars", []) if isinstance(j, dict)]
        name = info.get("name", "")
    meta.ids.update([mod_id, *provides])
    if top:
        meta.main_id, meta.name = mod_id, name
        meta.depends.update(deps)
    return jars


def _toml_meta(data: bytes, meta: ModMeta, top: bool) -> None:
    try:
        info = tomllib.loads(data.decode("utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, ValueError):
        return
    mods = info.get("mods") or []
    for m in mods:
        if m.get("modId"):
            meta.ids.add(m["modId"])
    if top and mods:
        meta.main_id = mods[0].get("modId", "")
        meta.name = mods[0].get("displayName", "")
        for mod_id, deps in (info.get("dependencies") or {}).items():
            if mod_id not in meta.ids:
                continue
            for d in deps if isinstance(deps, list) else []:
                required = d.get("mandatory", False) or d.get("type", "").lower() == "required"
                if required and d.get("side", "BOTH").upper() != "SERVER":
                    meta.depends.add(d.get("modId", ""))


def _scan_jar(zf: zipfile.ZipFile, meta: ModMeta, top: bool, depth: int = 0) -> None:
    names = set(zf.namelist())
    jars = []
    if "fabric.mod.json" in names:
        if top:
            meta.loaders.add("fabric")
        jars += _fabric_meta(zf.read("fabric.mod.json"), meta, top, "fabric")
    if "quilt.mod.json" in names:
        if top:
            meta.loaders.add("quilt")
        jars += _fabric_meta(zf.read("quilt.mod.json"), meta, top, "quilt")
    if "META-INF/neoforge.mods.toml" in names:
        if top:
            meta.loaders.add("neoforge")
        _toml_meta(zf.read("META-INF/neoforge.mods.toml"), meta, top)
    if "META-INF/mods.toml" in names:
        if top:
            # Ältere NeoForge-Versionen (1.20.x) nutzen ebenfalls mods.toml
            meta.loaders.update({"forge", "neoforge"})
        _toml_meta(zf.read("META-INF/mods.toml"), meta, top)
    if depth < 2:
        jars += [n for n in names if n.startswith("META-INF/jarjar/") and n.endswith(".jar")]
        for inner in jars:
            if inner in names:
                try:
                    with zipfile.ZipFile(io.BytesIO(zf.read(inner))) as nested:
                        _scan_jar(nested, meta, False, depth + 1)
                except (zipfile.BadZipFile, OSError, KeyError):
                    pass


def read_meta(path: Path, enabled: bool = True) -> ModMeta | None:
    meta = ModMeta(file=path.name, enabled=enabled)
    try:
        with zipfile.ZipFile(path) as zf:
            _scan_jar(zf, meta, True)
            if not meta.loaders and any(n.startswith("optifine/") or n == "Config.class" for n in zf.namelist()[:400]):
                meta.ids.add("optifine")
                meta.main_id, meta.name = "optifine", "OptiFine"
    except (zipfile.BadZipFile, OSError):
        return None
    meta.ids.discard("")
    if not meta.main_id and "optifine" in path.name.lower():
        meta.ids.add("optifine")
        meta.main_id, meta.name = "optifine", "OptiFine"
    return meta


def _loader_ok(loader: str, meta: ModMeta) -> bool:
    if not meta.loaders:
        return True   # keine Metadaten (z.B. reine Libraries) – nicht meckern
    if loader == "quilt":
        return bool(meta.loaders & {"quilt", "fabric"})   # Quilt lädt auch Fabric-Mods
    return loader in meta.loaders


def check(instance: Instance, extra: list[Path] | None = None) -> list[Issue]:
    """Prüft alle aktivierten Mods der Instanz (plus optional noch nicht installierte Dateien)."""
    if instance.loader == "vanilla":
        return []
    cs = instance.content["mods"]
    metas: list[ModMeta] = []
    for item in cs.items:
        if not item.enabled:
            continue
        path = cs.folder / item.disk_name
        if path.is_file():
            meta = read_meta(path)
            if meta:
                meta.name = item.name if item.source != "local" else (meta.name or item.name)
                metas.append(meta)
    for path in extra or []:
        meta = read_meta(path)
        if meta:
            metas.append(meta)
    return check_metas(instance.loader, metas)


def check_metas(loader: str, metas: list[ModMeta]) -> list[Issue]:
    issues: list[Issue] = []
    label = {"fabric": "Fabric", "quilt": "Quilt", "forge": "Forge", "neoforge": "NeoForge"}
    # 1) falscher Loader
    for m in metas:
        if not _loader_ok(loader, m):
            wanted = ", ".join(sorted(label.get(l, l) for l in m.loaders))
            issues.append(Issue("error", tr("{name} ist für {wanted}").format(name=m.name or m.file, wanted=wanted),
                                tr("Diese Instanz nutzt {loader}. Die Mod wird nicht geladen oder bringt das Spiel "
                                   "zum Absturz.").format(loader=label.get(loader, loader)), [m.file], "loader"))
    usable = [m for m in metas if _loader_ok(loader, m)]
    # 2) doppelt
    by_id: dict[str, list] = {}
    for m in usable:
        if m.main_id:
            by_id.setdefault(m.main_id, []).append(m)
    for mod_id, group in by_id.items():
        if len(group) > 1:
            issues.append(Issue("error", tr("{name} ist {n}× installiert").format(name=group[0].name or mod_id, n=len(group)),
                                tr("Lass nur eine Version aktiviert – sonst startet das Spiel nicht."),
                                [m.file for m in group], "duplicate"))
    # 3) fehlende Abhängigkeiten
    provided = set(BUILTIN)
    for m in usable:
        provided |= m.ids
    if loader in ("fabric", "quilt"):
        # Fabric API stellt viele Module bereit (fabric-*-api-v1 …)
        has_fabric_api = any(i.startswith("fabric-api") or i == "fabric" for i in provided)
    else:
        has_fabric_api = False
    for m in usable:
        missing = []
        for dep in sorted(m.depends):
            if not dep or dep in provided:
                continue
            if has_fabric_api and (dep == "fabric" or re.match(r"fabric-.*-v\d+$", dep) or dep.startswith("fabric-")):
                continue
            if dep == "fabric" and "fabric-api" in provided:
                continue
            missing.append(dep)
        if missing:
            issues.append(Issue("warning", tr("{name} braucht: {deps}").format(name=m.name or m.file, deps=", ".join(missing)),
                                tr("Installiere die fehlenden Mods über „Entdecken“."), [m.file], "missing", missing))
    # 4) bekannte Konflikte
    present = {}
    for m in usable:
        for i in m.ids:
            present.setdefault(i, m)
    for group_a, group_b, why in CONFLICTS:
        a = next((present[i] for i in group_a if i in present), None)
        b = next((present[i] for i in group_b if i in present), None)
        if a and b and a is not b:
            issues.append(Issue("error", tr("{a} und {b} vertragen sich nicht").format(a=a.name or a.file, b=b.name or b.file),
                                why, [a.file, b.file], "conflict"))
    issues.sort(key=lambda i: i.severity != "error")
    return issues
