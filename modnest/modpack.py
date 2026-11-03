"""Modpacks teilen: Export/Import im Modrinth-Format (.mrpack) und im CurseForge-Format (.zip).

Beide Formate werden von den meisten Launchern verstanden (Modrinth App, Prism, ATLauncher,
CurseForge App, MultiMC …). Dateien, die auf der jeweiligen Plattform nicht gefunden werden,
landen als „Overrides“ direkt im Paket, damit das Pack trotzdem vollständig ist.
"""
import hashlib
import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .categorize import guess_category
from .instances import KINDS, Instance, Mod, create_instance
from .sources.base import DownloadJob, SourceError, download, download_many, session
from .sources.curseforge import API as CF_API, CLASS_IDS
from .sources.modrinth import API as MODRINTH_API
from .i18n import tr

MR_LOADER_KEYS = {"fabric": "fabric-loader", "quilt": "quilt-loader", "forge": "forge", "neoforge": "neoforge"}
# Ordner, die als Overrides mitgenommen werden (Einstellungen der Mods usw.)
OVERRIDE_DIRS = ("config", "kubejs", "defaultconfigs", "scripts")
OVERRIDE_FILES = ("options.txt", "servers.dat")
@dataclass
class ManualFile:
    """Datei, die der Autor nur über die Webseite freigibt (CurseForge)."""
    name: str
    filename: str
    folder: str
    url: str
    sha1: str = ""


ALLOWED_DOWNLOAD_HOSTS = ("cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com",
                          "edge.forgecdn.net", "mediafilez.forgecdn.net")


# --- Hilfsfunktionen ------------------------------------------------------------
def _hashes(path: Path) -> tuple[str, str]:
    sha1, sha512 = hashlib.sha1(), hashlib.sha512()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            sha1.update(chunk)
            sha512.update(chunk)
    return sha1.hexdigest(), sha512.hexdigest()


def _murmur2_fingerprint(path: Path) -> int:
    """CurseForge-Fingerprint: MurmurHash2 (Seed 1) über die Datei ohne Leerzeichen/Zeilenumbrüche."""
    data = bytes(b for b in path.read_bytes() if b not in (9, 10, 13, 32))
    m, length = 0x5BD1E995, len(data)
    h = (1 ^ length) & 0xFFFFFFFF
    i = 0
    while length - i >= 4:
        k = int.from_bytes(data[i:i + 4], "little")
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> 24
        k = (k * m) & 0xFFFFFFFF
        h = ((h * m) & 0xFFFFFFFF) ^ k
        i += 4
    rest = length - i
    if rest == 3:
        h ^= data[i + 2] << 16
    if rest >= 2:
        h ^= data[i + 1] << 8
    if rest >= 1:
        h ^= data[i]
        h = (h * m) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h


def loader_version_of(instance: Instance) -> str:
    """Loader-Version aus der Instanz bzw. der installierten Versions-ID."""
    if instance.loader_version:
        return instance.loader_version
    vid = instance.version_id
    patterns = {
        "fabric": r"fabric-loader-([^-]+)-",
        "quilt": r"quilt-loader-([^-]+)-",
        "forge": r"forge-?([\d.]+)$",
        "neoforge": r"neoforge-([\d.]+(?:-beta)?)",
    }
    match = re.search(patterns.get(instance.loader, "$^"), vid)
    return match.group(1) if match else ""


def _content_files(instance: Instance) -> list[tuple[str, Path, Mod]]:
    """(Pfad im Pack, Datei, Eintrag) aller aktivierten Dateien (Ordner-Packs werden übersprungen)."""
    result = []
    for kind, info in KINDS.items():
        cs = instance.content[kind]
        for item in cs.items:
            path = cs.folder / item.disk_name
            if item.enabled and path.is_file():
                result.append((f"{info['folder']}/{item.file}", path, item))
    return result


def _add_overrides(zf: zipfile.ZipFile, instance: Instance, extra: list[tuple[str, Path]], prefix: str) -> None:
    for name in OVERRIDE_DIRS:
        folder = instance.path / name
        if folder.is_dir():
            for file in folder.rglob("*"):
                if file.is_file():
                    zf.write(file, f"{prefix}/{file.relative_to(instance.path).as_posix()}")
    for name in OVERRIDE_FILES:
        file = instance.path / name
        if file.is_file():
            zf.write(file, f"{prefix}/{name}")
    for rel, file in extra:
        zf.write(file, f"{prefix}/{rel}")


# --- Export ---------------------------------------------------------------------
def export_mrpack(instance: Instance, target: Path, version: str = "1.0.0", summary: str = "",
                  progress=lambda *a: None) -> dict:
    """Exportiert als .mrpack. Gibt eine Statistik zurück (verlinkt / eingebettet)."""
    files = _content_files(instance)
    progress(tr("Berechne Prüfsummen …"), 0, 0)
    hashes = {rel: _hashes(path) for rel, path, _ in files}
    known: dict[str, dict] = {}
    if hashes:
        resp = session.post(f"{MODRINTH_API}/version_files",
                            json={"hashes": [h[0] for h in hashes.values()], "algorithm": "sha1"}, timeout=30)
        if resp.ok:
            known = resp.json()
    index_files, overrides = [], []
    for rel, path, _ in files:
        sha1, sha512 = hashes[rel]
        version_data = known.get(sha1)
        url = None
        if version_data:
            url = next((f["url"] for f in version_data.get("files", []) if f.get("hashes", {}).get("sha1") == sha1), None)
        if url:
            index_files.append({
                "path": rel, "hashes": {"sha1": sha1, "sha512": sha512},
                "env": {"client": "required", "server": "required" if rel.startswith("mods/") else "unsupported"},
                "downloads": [url], "fileSize": path.stat().st_size,
            })
        else:
            overrides.append((rel, path))
    deps = {"minecraft": instance.mc_version}
    if instance.loader in MR_LOADER_KEYS:
        lv = loader_version_of(instance)
        if not lv:
            raise SourceError(tr("Die Loader-Version ist unbekannt. Starte die Instanz einmal, dann klappt der Export."))
        deps[MR_LOADER_KEYS[instance.loader]] = lv
    index = {"formatVersion": 1, "game": "minecraft", "versionId": version, "name": instance.name,
             "summary": summary or "Erstellt mit ModNest", "files": index_files, "dependencies": deps}
    progress(tr("Schreibe Paket …"), 0, 0)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("modrinth.index.json", json.dumps(index, indent=2, ensure_ascii=False))
        _add_overrides(zf, instance, overrides, "overrides")
        if instance.icon_path:
            zf.write(instance.icon_path, "overrides/icon.png")
    return {"linked": len(index_files), "embedded": len(overrides)}


def export_curseforge(instance: Instance, target: Path, settings, version: str = "1.0.0", author: str = "",
                      progress=lambda *a: None) -> dict:
    """Exportiert im CurseForge-Format (manifest.json). Ohne API-Key werden alle Dateien eingebettet."""
    files = _content_files(instance)
    key = settings.curseforge_api_key.strip()
    matches: dict[int, tuple[int, int]] = {}
    fingerprints = {}
    if key and files:
        progress(tr("Berechne CurseForge-Fingerprints …"), 0, 0)
        fingerprints = {rel: _murmur2_fingerprint(path) for rel, path, _ in files}
        resp = session.post(f"{CF_API}/fingerprints/432", json={"fingerprints": list(fingerprints.values())},
                            headers={"x-api-key": key}, timeout=30)
        if resp.ok:
            for m in resp.json().get("data", {}).get("exactMatches", []):
                f = m.get("file") or {}
                matches[int(f.get("fileFingerprint", 0))] = (int(m["id"]), int(f["id"]))
    manifest_files, overrides = [], []
    for rel, path, _ in files:
        hit = matches.get(fingerprints.get(rel, -1))
        if hit:
            manifest_files.append({"projectID": hit[0], "fileID": hit[1], "required": True})
        else:
            overrides.append((rel, path))
    loaders = []
    if instance.loader in MR_LOADER_KEYS:
        lv = loader_version_of(instance)
        if not lv:
            raise SourceError(tr("Die Loader-Version ist unbekannt. Starte die Instanz einmal, dann klappt der Export."))
        loaders.append({"id": f"{instance.loader}-{lv}", "primary": True})
    manifest = {"minecraft": {"version": instance.mc_version, "modLoaders": loaders},
                "manifestType": "minecraftModpack", "manifestVersion": 1, "name": instance.name,
                "version": version, "author": author or "ModNest", "files": manifest_files, "overrides": "overrides"}
    progress(tr("Schreibe Paket …"), 0, 0)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        _add_overrides(zf, instance, overrides, "overrides")
    return {"linked": len(manifest_files), "embedded": len(overrides)}


# --- Import ---------------------------------------------------------------------
def detect_pack(path: Path) -> str | None:
    """'mrpack', 'curseforge' oder None."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return None
    if "modrinth.index.json" in names:
        return "mrpack"
    if "manifest.json" in names:
        return "curseforge"
    return None


def _safe_target(base: Path, rel: str) -> Path:
    target = (base / rel).resolve()
    if base.resolve() not in target.parents and target != base.resolve():
        raise SourceError(tr("Ungültiger Pfad im Paket: {path}").format(path=rel))
    return target


def _apply_modrinth_metadata(instance: Instance) -> None:
    """Ergänzt Name, Icon und Kategorie der Dateien über Modrinth (per Prüfsumme)."""
    by_sha = {}
    for kind in KINDS:
        cs = instance.content[kind]
        for item in cs.items:
            path = cs.folder / item.disk_name
            if path.is_file() and item.source == "local":
                by_sha[_hashes(path)[0]] = (kind, item)
    if not by_sha:
        return
    resp = session.post(f"{MODRINTH_API}/version_files", json={"hashes": list(by_sha), "algorithm": "sha1"}, timeout=30)
    if not resp.ok:
        return
    versions = resp.json()
    ids = list({v["project_id"] for v in versions.values()})
    projects = {}
    for i in range(0, len(ids), 100):
        r = session.get(f"{MODRINTH_API}/projects", params={"ids": json.dumps(ids[i:i + 100])}, timeout=30)
        if r.ok:
            projects.update({p["id"]: p for p in r.json()})
    for sha, version in versions.items():
        kind, item = by_sha[sha]
        proj = projects.get(version["project_id"])
        if not proj:
            continue
        item.name = proj.get("title", item.name)
        item.source, item.project_id = "modrinth", proj["id"]
        item.version_id, item.version_name = version["id"], version.get("version_number", "")
        item.icon_url = proj.get("icon_url") or ""
        item.description = proj.get("description", "")
        item.url = f"https://modrinth.com/{proj.get('project_type', 'mod')}/{proj.get('slug', proj['id'])}"
        cats = list(proj.get("categories", [])) + list(proj.get("additional_categories", []))
        item.category = guess_category(cats, instance.content[kind].category_names(), kind)


@dataclass
class PlanFile:
    """Eine Datei, die direkt an ihren Platz in der Instanz geladen wird."""
    rel: str
    url: str
    sha1: str = ""
    md5: str = ""
    label: str = ""


@dataclass
class Archive:
    """Ein ZIP, dessen Inhalt (ab prefix) in die Instanz entpackt wird – lokal (path) oder per url."""
    path: Path | None = None
    url: str = ""
    sha1: str = ""
    md5: str = ""
    prefix: str = ""       # Unterordner im ZIP, z.B. "overrides" ("" = alles)
    dest: str = ""         # Zielordner in der Instanz ("" = Hauptordner)


@dataclass
class MetaInfo:
    """Bekannte Infos zu einer Datei (Name, Icon, Quelle), damit sie hübsch in der Liste steht."""
    name: str
    source: str
    project_id: str
    version_id: str = ""
    version_name: str = ""
    icon_url: str = ""
    url: str = ""
    description: str = ""
    categories: list = field(default_factory=list)


@dataclass
class PackPlan:
    """Bauplan eines Modpacks – unabhängig davon, von welcher Plattform es stammt."""
    name: str
    mc_version: str
    loader: str = "vanilla"
    loader_version: str = ""
    files: list = field(default_factory=list)          # PlanFile
    archives: list = field(default_factory=list)       # Archive
    manual: list = field(default_factory=list)         # ManualFile
    meta: dict = field(default_factory=dict)           # rel-Pfad → MetaInfo
    icon_url: str = ""
    ram_mb: int = 0                                    # empfohlener Arbeitsspeicher
    finalize: object = None                            # optional: fn(instance, plan) nach dem Entpacken


# Dateien, die bei einem Update nicht überschrieben werden (deine Einstellungen)
KEEP_ON_UPDATE = {"options.txt", "optionsof.txt", "optionsshaders.txt", "servers.dat"}


def _rel(base: Path, path: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def _extract(zf: zipfile.ZipFile, prefix: str, dest: Path, base: Path, skip_existing: set) -> list:
    """Entpackt Einträge unter prefix nach dest; gibt die geschriebenen Pfade relativ zu base zurück."""
    written = []
    prefix = prefix.strip("/")
    for member in zf.infolist():
        if member.is_dir():
            continue
        name = member.filename.replace(chr(92), "/")
        if prefix:
            if not name.startswith(prefix + "/"):
                continue
            name = name[len(prefix) + 1:]
        if not name.strip("/"):
            continue
        out = _safe_target(dest, name)
        rel = _rel(base, out)
        if rel in skip_existing and out.exists():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
        written.append(rel)
    return written


def backup_before_update(inst: Instance, settings) -> Path:
    """Sichert Mods, Configs und instance.json vor einem Modpack-Update als ZIP."""
    from .backup import backup_root
    folder = backup_root(settings) / "Modpack-Updates"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    target = folder / f"{re.sub(r'[^A-Za-z0-9 _.-]', '_', inst.name)}_{stamp}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in ("mods", "config", "defaultconfigs", "kubejs", "resourcepacks", "shaderpacks"):
            folder_path = inst.path / sub
            if folder_path.is_dir():
                for file in folder_path.rglob("*"):
                    if file.is_file():
                        zf.write(file, file.relative_to(inst.path).as_posix())
        for name in ("instance.json", "options.txt"):
            if (inst.path / name).is_file():
                zf.write(inst.path / name, name)
    return target


def build_instance(plan: PackPlan, settings, progress=lambda *a: None, name: str | None = None,
                   origin: dict | None = None, instance: Instance | None = None) -> Instance:
    """Legt aus einem Bauplan eine Instanz an – oder aktualisiert eine bestehende (instance=…).

    Bei einem Update werden alte Dateien des Packs entfernt; deine eigenen Mods, Welten und
    Einstellungen bleiben erhalten.
    """
    updating = instance is not None
    inst = instance or create_instance(name or plan.name or "Modpack", plan.mc_version, plan.loader)
    work = inst.path / ".modnest-tmp"
    old_files = set((inst.pack or {}).get("files", [])) if updating else set()
    old_disabled = {rel for rel in old_files if (inst.path / (rel + ".disabled")).exists()}
    old_by_project = {}
    if updating:
        for kind in KINDS:
            for item in inst.content[kind].items:
                if item.project_id:
                    old_by_project[(item.source, item.project_id)] = item.category
    try:
        work.mkdir(exist_ok=True)
        jobs = [DownloadJob(f.url, _safe_target(inst.path, f.rel), f.sha1, f.label, f.md5) for f in plan.files]
        for n, arc in enumerate(plan.archives):
            if arc.path is None:
                arc.path = work / f"archive-{n}.zip"
                jobs.append(DownloadJob(arc.url, arc.path, arc.sha1, Path(arc.url.split("?")[0]).name, arc.md5))
        download_many(jobs, progress)
        written = {_rel(inst.path, _safe_target(inst.path, f.rel)) for f in plan.files}
        progress(tr("Entpacke Dateien …"), 0, 0)
        skip = KEEP_ON_UPDATE if updating else set()
        for arc in plan.archives:
            with zipfile.ZipFile(arc.path) as zf:
                dest = _safe_target(inst.path, arc.dest) if arc.dest else inst.path
                written.update(_extract(zf, arc.prefix, dest, inst.path, skip))
        # Alte Pack-Dateien entfernen, die es in der neuen Version nicht mehr gibt
        for rel in old_files - written:
            for candidate in (inst.path / rel, inst.path / (rel + ".disabled")):
                if candidate.is_file():
                    candidate.unlink()
        # Von dir deaktivierte Pack-Mods bleiben deaktiviert
        for rel in old_disabled & written:
            path = inst.path / rel
            if path.exists():
                path.replace(inst.path / (rel + ".disabled"))
        if plan.finalize:
            plan.finalize(inst, plan)
        if (inst.mc_version, inst.loader, inst.loader_version) != (plan.mc_version, plan.loader, plan.loader_version):
            inst.version_id = ""
        inst.mc_version, inst.loader, inst.loader_version = plan.mc_version, plan.loader, plan.loader_version
        if not updating and plan.ram_mb > settings.ram_mb:
            inst.ram_mb = plan.ram_mb
        inst.pack = dict(origin or {})
        inst.pack["files"] = sorted(written)
        icon = inst.path / "icon.png"
        if not inst.icon and plan.icon_url and not icon.exists():
            try:
                download(plan.icon_url, icon, retries=1)
            except Exception:  # noqa: BLE001 – das Icon ist nur Deko
                pass
        if icon.exists() and not inst.icon:
            inst.icon = "icon.png"
        inst.sync_with_disk()
        _apply_meta(inst, plan.meta)
        progress(tr("Ergänze Mod-Infos …"), 0, 0)
        try:
            _apply_modrinth_metadata(inst)
        except (OSError, ValueError, SourceError, requests.RequestException):
            pass
        for kind in KINDS:
            for item in inst.content[kind].items:
                old = old_by_project.get((item.source, item.project_id)) if item.project_id else None
                if old and old in inst.content[kind].category_names():
                    item.category = old
        inst.save()
    except BaseException:
        if not updating:
            shutil.rmtree(inst.path, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    inst.import_manual = plan.manual
    return inst


def _apply_meta(inst: Instance, meta: dict) -> None:
    for kind, info in KINDS.items():
        cs = inst.content[kind]
        for item in cs.items:
            known = meta.get(f"{info['folder']}/{item.file}")
            if known is None or item.source != "local":
                continue
            item.name, item.source, item.project_id = known.name, known.source, known.project_id
            item.version_id, item.version_name = known.version_id, known.version_name
            item.icon_url, item.url, item.description = known.icon_url, known.url, known.description
            if known.categories:
                item.category = guess_category(known.categories, cs.category_names(), kind)


def plan_mrpack(path: Path) -> PackPlan:
    with zipfile.ZipFile(path) as zf:
        index = json.loads(zf.read("modrinth.index.json"))
    deps = index.get("dependencies", {})
    loader, loader_version = "vanilla", ""
    for key, value in MR_LOADER_KEYS.items():
        if value in deps:
            loader, loader_version = key, deps[value]
    plan = PackPlan(name=index.get("name", "Modpack"), mc_version=deps.get("minecraft", ""),
                    loader=loader, loader_version=loader_version)
    for f in index.get("files", []):
        if (f.get("env") or {}).get("client", "required") == "unsupported":
            continue
        url = next((u for u in f.get("downloads", []) if any(h in u for h in ALLOWED_DOWNLOAD_HOSTS)), None)
        if url:
            plan.files.append(PlanFile(f["path"], url, f.get("hashes", {}).get("sha1", "")))
    plan.archives = [Archive(path=path, prefix="overrides"), Archive(path=path, prefix="client-overrides")]
    return plan


def cf_sha1(info: dict) -> str:
    return next((h.get("value", "") for h in info.get("hashes", []) if h.get("algo") == 1), "")


def cf_resolve_files(file_ids: list, mod_ids: list, key: str) -> tuple:
    """Holt Datei- und Projekt-Infos von CurseForge (in Blöcken)."""
    headers = {"x-api-key": key}
    files, mods = {}, {}
    for i in range(0, len(file_ids), 500):
        r = session.post(f"{CF_API}/mods/files", json={"fileIds": file_ids[i:i + 500]}, headers=headers, timeout=30)
        r.raise_for_status()
        files.update({f["id"]: f for f in r.json()["data"]})
    ids = list(dict.fromkeys(mod_ids))
    for i in range(0, len(ids), 500):
        r = session.post(f"{CF_API}/mods", json={"modIds": ids[i:i + 500]}, headers=headers, timeout=30)
        r.raise_for_status()
        mods.update({m["id"]: m for m in r.json()["data"]})
    return files, mods


def cf_add_files(plan: PackPlan, entries: list, key: str, default_folder: str = "mods") -> None:
    """Fügt CurseForge-Dateien [(Projekt-ID, Datei-ID)] zum Bauplan hinzu."""
    if not entries:
        return
    file_info, mod_info = cf_resolve_files([f for _, f in entries], [p for p, _ in entries], key)
    folders = {cid: KINDS[k]["folder"] for k, cid in CLASS_IDS.items()}
    for project_id, file_id in entries:
        info = file_info.get(file_id)
        mod = mod_info.get(project_id, {})
        if not info:
            continue
        folder = folders.get(mod.get("classId"), default_folder)
        rel = f"{folder}/{info['fileName']}"
        page = (mod.get("links") or {}).get("websiteUrl", "").rstrip("/")
        if not info.get("downloadUrl"):
            plan.manual.append(ManualFile(name=mod.get("name", info["fileName"]), filename=info["fileName"],
                                          folder=folder, url=f"{page}/files/{file_id}" if page else "",
                                          sha1=cf_sha1(info)))
            continue
        plan.files.append(PlanFile(rel, info["downloadUrl"], cf_sha1(info), label=mod.get("name", "")))
        plan.meta[rel] = MetaInfo(
            name=mod.get("name", info["fileName"]), source="curseforge", project_id=str(project_id),
            version_id=str(file_id), version_name=info.get("displayName", ""),
            icon_url=(mod.get("logo") or {}).get("thumbnailUrl", ""), url=page,
            description=mod.get("summary", ""), categories=[c.get("name", "") for c in mod.get("categories", [])])


def plan_curseforge(path: Path, key: str) -> PackPlan:
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    mc = manifest.get("minecraft", {})
    loader, loader_version = "vanilla", ""
    for entry in mc.get("modLoaders", []):
        lid = entry.get("id", "")
        for k in ("neoforge", "fabric", "quilt", "forge"):
            if lid.startswith(k + "-"):
                loader, loader_version = k, lid[len(k) + 1:]
                break
        if loader != "vanilla":
            break
    files = manifest.get("files", [])
    if files and not key:
        raise SourceError(tr("Für CurseForge-Modpacks wird ein CurseForge-API-Key benötigt (⚙ Einstellungen)."))
    plan = PackPlan(name=manifest.get("name", "Modpack"), mc_version=mc.get("version", ""),
                    loader=loader, loader_version=loader_version)
    cf_add_files(plan, [(int(f["projectID"]), int(f["fileID"])) for f in files if f.get("required", True)], key)
    plan.archives = [Archive(path=path, prefix=manifest.get("overrides") or "overrides")]
    return plan


def import_pack(path: Path, settings, progress=lambda *a: None, name: str | None = None) -> Instance:
    kind = detect_pack(path)
    if kind is None:
        raise SourceError(tr("Diese Datei ist kein Modpack (.mrpack oder CurseForge-ZIP)."))
    plan = plan_mrpack(path) if kind == "mrpack" else plan_curseforge(path, settings.curseforge_api_key.strip())
    return build_instance(plan, settings, progress, name)
