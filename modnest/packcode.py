"""Pack-Code: eine Instanz als kurzen Text teilen (z.B. in Discord). Wer ihn in ModNest einlöst, bekommt
dieselbe Minecraft-Version, denselben Loader, dasselbe Modpack und dieselben Mods in denselben Versionen.

Der Code enthält nur IDs von Modrinth/CurseForge – keine Dateien. Lokale Dateien ohne Quelle werden nicht
übertragen und beim Erstellen aufgelistet."""
import base64
import json
import re
import zlib
from types import SimpleNamespace

from . import installer, packs
from .i18n import tr
from .instances import KINDS, create_instance
from .sources import SourceError, get_source
from .sources import modrinth

PREFIX = "MODNEST1:"
_KIND = {"mods": "m", "resourcepacks": "r", "shaderpacks": "s"}
_SRC = {"modrinth": "mr", "curseforge": "cf"}
END = "."
_PATTERN = re.compile(r"MODNEST1:([A-Za-z0-9_-]+)")


def make(inst) -> tuple[str, list[str]]:
    """(Code, Namen der Einträge, die nicht mitkommen)"""
    pack = inst.pack or {}
    pack_files = set(pack.get("files", []))
    data = {"v": 1, "n": inst.name, "mc": inst.mc_version, "l": inst.loader}
    if pack.get("provider"):
        data["p"] = {k: pack[k] for k in ("provider", "id", "name", "version_id", "version_name", "icon_url", "url",
                                          "extra") if pack.get(k)}
    cats, items, disabled, skipped = [], [], [], []
    for kind, content in inst.content.items():
        folder = KINDS[kind]["folder"]
        for m in content.items:
            rel = f"{folder}/{m.file}"
            if rel in pack_files:
                if not m.enabled:
                    disabled.append(rel)
                continue
            if m.source not in _SRC or not m.project_id or not m.version_id:
                skipped.append(m.name or m.file)
                continue
            if m.category not in cats:
                cats.append(m.category)
            items.append([_KIND[kind], _SRC[m.source], m.project_id, m.version_id, cats.index(m.category),
                          int(m.enabled)])
    data["c"], data["i"] = cats, items
    if disabled:
        data["d"] = disabled
    raw = zlib.compress(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), 9)
    # Der Punkt am Ende markiert das Code-Ende, damit Text dahinter („viel Spaß“) nicht mitgelesen wird
    return PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=") + END, skipped


def parse(text: str) -> dict:
    """Findet den Code auch mitten in einer Nachricht (auch wenn Discord ihn umgebrochen hat)."""
    text = text or ""
    start = text.find(PREFIX)
    if start < 0:
        raise SourceError(tr("Das ist kein gültiger Pack-Code. Er beginnt mit „MODNEST1:“."))
    rest = text[start:]
    end = rest.find(END, len(PREFIX))
    if end >= 0:
        rest = rest[:end]
    match = _PATTERN.match(re.sub(r"\s+", "", rest))
    if not match:
        raise SourceError(tr("Das ist kein gültiger Pack-Code. Er beginnt mit „MODNEST1:“."))
    body = match.group(1)
    try:
        data = json.loads(zlib.decompress(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))).decode("utf-8"))
    except (ValueError, zlib.error) as exc:
        raise SourceError(tr("Der Pack-Code ist unvollständig oder beschädigt. Wurde er ganz kopiert?")) from exc
    if not isinstance(data, dict) or data.get("v") != 1 or not data.get("mc"):
        raise SourceError(tr("Dieser Pack-Code stammt aus einer neueren ModNest-Version. Bitte ModNest aktualisieren."))
    return data


def summary(data: dict) -> dict:
    kinds = {"m": 0, "r": 0, "s": 0}
    for it in data.get("i", []):
        kinds[it[0]] = kinds.get(it[0], 0) + 1
    return {"name": data.get("n", ""), "mc": data["mc"], "loader": data.get("l", "vanilla"),
            "pack": (data.get("p") or {}).get("name", ""), "pack_version": (data.get("p") or {}).get("version_name", ""),
            "mods": kinds["m"], "resourcepacks": kinds["r"], "shaderpacks": kinds["s"],
            "needs_curseforge": any(it[1] == "cf" for it in data.get("i", []))
            or (data.get("p") or {}).get("provider") == "curseforge"}


def _release(source_key: str, project_id: str, version_id: str, inst, kind: str, settings):
    """Genau diese Version – oder (falls weg) die neueste passende. (Release, exakt?)"""
    if source_key == "modrinth":
        try:
            return modrinth._release_from_version(modrinth._get(f"/version/{version_id}")), True
        except (SourceError, OSError):
            pass
    else:
        versions = get_source(source_key, settings).list_versions(project_id, inst.mc_version, inst.loader, kind)
        exact = next((v for v in versions if v.version_id == version_id), None)
        if exact:
            return exact, True
    return get_source(source_key, settings).resolve(project_id, inst.mc_version, inst.loader, kind), False


def redeem(data: dict, settings, progress, name: str):
    """Legt die Instanz an. Gibt (Instanz, [Hinweise]) zurück."""
    notes = []
    origin = data.get("p")
    if origin:
        progress(tr("Suche Modpack {name} …").format(name=origin.get("name", "")), 0, 0)
        pack = packs.pack_from_instance(SimpleNamespace(pack=origin, name=origin.get("name", name),
                                                        mc_version=data["mc"]))
        if pack is None:
            raise SourceError(tr("Diese Modpack-Quelle wird nicht unterstützt."))
        versions = packs.provider(pack.provider).versions(pack, settings)
        version = next((v for v in versions if str(v.version_id) == str(origin.get("version_id"))), None)
        if version is None:
            version = next((v for v in versions if v.mc_version == data["mc"]), None) or (versions[0] if versions else None)
            if version is None:
                raise SourceError(tr("Für dieses Modpack gibt es keine installierbare Version."))
            notes.append(tr("Modpack-Version {old} gibt es nicht mehr – stattdessen {new} installiert.").format(
                old=origin.get("version_name", "?"), new=version.name))
        inst = packs.install(pack, version, settings, progress, name)
        for rel in data.get("d", []):
            folder, _, file = rel.partition("/")
            kind = next((k for k, info in KINDS.items() if info["folder"] == folder), None)
            if kind and inst.content[kind].find_file(file):
                inst.content[kind].set_enabled(file, False)
    else:
        inst = create_instance(name, data["mc"], data.get("l", "vanilla"))
    cats = data.get("c", [])
    kinds = {v: k for k, v in _KIND.items()}
    sources = {v: k for k, v in _SRC.items()}
    items = data.get("i", [])
    for n, (k, s, pid, vid, ci, enabled) in enumerate(items, start=1):
        kind, source_key = kinds.get(k), sources.get(s)
        if not kind or not source_key:
            continue
        category = cats[ci] if 0 <= ci < len(cats) else None
        content = inst.content[kind]
        if category:
            content.add_category(category)
        progress(tr("Installiere Inhalt {n} von {total} …").format(n=n, total=len(items)), n, len(items))
        try:
            if source_key == "curseforge" and not settings.curseforge_api_key.strip():
                raise SourceError(tr("CurseForge-API-Key fehlt"))
            project = get_source(source_key, settings).get_project(pid, kind)
            release, exact = _release(source_key, pid, vid, inst, kind, settings)
            installer.install_project(inst, project, settings, category, lambda *a: None, release, pin=False)
            if not exact:
                notes.append(tr("{title}: genaue Version nicht mehr verfügbar – neueste passende installiert.").format(
                    title=project.title))
            if not enabled:
                item = content.find_project(source_key, pid)
                if item:
                    content.set_enabled(item.file, False)
        except (SourceError, OSError, ValueError) as exc:
            notes.append(f"{pid}: {exc}")
    inst.save()
    return inst, notes


__all__ = ["make", "parse", "summary", "redeem"]
