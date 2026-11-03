"""Modpacks teilen: Export/Import im Modrinth-Format (.mrpack) und im CurseForge-Format (.zip).

Beide Formate werden von den meisten Launchern verstanden (Modrinth App, Prism, ATLauncher,
CurseForge App, MultiMC …). Dateien, die auf der jeweiligen Plattform nicht gefunden werden,
landen als „Overrides“ direkt im Paket, damit das Pack trotzdem vollständig ist.
"""
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

from .categorize import guess_category
from .instances import KINDS, Instance, Mod, create_instance
from .sources.base import SourceError, download, session
from .sources.curseforge import API as CF_API, CLASS_IDS
from .sources.modrinth import API as MODRINTH_API
from .i18n import tr

MR_LOADER_KEYS = {"fabric": "fabric-loader", "quilt": "quilt-loader", "forge": "forge", "neoforge": "neoforge"}
# Ordner, die als Overrides mitgenommen werden (Einstellungen der Mods usw.)
OVERRIDE_DIRS = ("config", "kubejs", "defaultconfigs", "scripts")
OVERRIDE_FILES = ("options.txt", "servers.dat")
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


def _extract_overrides(zf: zipfile.ZipFile, prefixes: tuple[str, ...], dest: Path) -> None:
    for member in zf.infolist():
        for prefix in prefixes:
            if member.filename.startswith(prefix + "/") and not member.is_dir():
                rel = member.filename[len(prefix) + 1:]
                if not rel:
                    continue
                out = _safe_target(dest, rel)
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)


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


def import_pack(path: Path, settings, progress=lambda *a: None, name: str | None = None) -> Instance:
    kind = detect_pack(path)
    if kind is None:
        raise SourceError(tr("Diese Datei ist kein Modpack (.mrpack oder CurseForge-ZIP)."))
    with zipfile.ZipFile(path) as zf:
        if kind == "mrpack":
            return _import_mrpack(zf, settings, progress, name)
        return _import_curseforge(zf, settings, progress, name)


def _new_instance(name: str, mc: str, loader: str, loader_version: str) -> Instance:
    inst = create_instance(name, mc, loader)
    inst.loader_version = loader_version
    inst.save()
    return inst


def _import_mrpack(zf: zipfile.ZipFile, settings, progress, name) -> Instance:
    index = json.loads(zf.read("modrinth.index.json"))
    deps = index.get("dependencies", {})
    loader, loader_version = "vanilla", ""
    for key, value in MR_LOADER_KEYS.items():
        if value in deps:
            loader, loader_version = key, deps[value]
    inst = _new_instance(name or index.get("name", "Importiertes Modpack"), deps.get("minecraft", ""), loader, loader_version)
    try:
        files = [f for f in index.get("files", []) if (f.get("env") or {}).get("client", "required") != "unsupported"]
        for n, f in enumerate(files, 1):
            target = _safe_target(inst.path, f["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            url = next((u for u in f.get("downloads", []) if any(h in u for h in ALLOWED_DOWNLOAD_HOSTS)), None)
            if not url:
                continue
            progress(tr("Lade {file} ({n}/{total}) …").format(file=target.name, n=n, total=len(files)), n, len(files))
            download(url, target)
            if hashlib.sha1(target.read_bytes()).hexdigest() != f.get("hashes", {}).get("sha1", ""):
                target.unlink(missing_ok=True)
                raise SourceError(tr("Prüfsumme von {file} stimmt nicht – Download abgebrochen.").format(file=target.name))
        progress(tr("Entpacke Overrides …"), 0, 0)
        _extract_overrides(zf, ("overrides", "client-overrides"), inst.path)
        _finish_import(inst, progress)
    except Exception:
        shutil.rmtree(inst.path, ignore_errors=True)
        raise
    return inst


def _import_curseforge(zf: zipfile.ZipFile, settings, progress, name) -> Instance:
    manifest = json.loads(zf.read("manifest.json"))
    mc = manifest.get("minecraft", {})
    loader, loader_version = "vanilla", ""
    for entry in mc.get("modLoaders", []):
        lid = entry.get("id", "")
        for key in ("neoforge", "fabric", "quilt", "forge"):
            if lid.startswith(key + "-"):
                loader, loader_version = key, lid[len(key) + 1:]
                break
        if loader != "vanilla":
            break
    files = manifest.get("files", [])
    key = settings.curseforge_api_key.strip()
    if files and not key:
        raise SourceError(tr("Für CurseForge-Modpacks wird ein CurseForge-API-Key benötigt (⚙ Einstellungen)."))
    inst = _new_instance(name or manifest.get("name", "Importiertes Modpack"), mc.get("version", ""), loader, loader_version)
    manual: list[str] = []
    try:
        if files:
            headers = {"x-api-key": key}
            file_ids = [f["fileID"] for f in files]
            mod_ids = [f["projectID"] for f in files]
            r = session.post(f"{CF_API}/mods/files", json={"fileIds": file_ids}, headers=headers, timeout=30)
            r.raise_for_status()
            file_info = {f["id"]: f for f in r.json()["data"]}
            r = session.post(f"{CF_API}/mods", json={"modIds": mod_ids}, headers=headers, timeout=30)
            r.raise_for_status()
            mod_info = {m["id"]: m for m in r.json()["data"]}
            folders = {cid: KINDS[k]["folder"] for k, cid in CLASS_IDS.items()}
            for n, entry in enumerate(files, 1):
                info = file_info.get(entry["fileID"])
                mod = mod_info.get(entry["projectID"], {})
                if not info:
                    continue
                folder = folders.get(mod.get("classId"), "mods")
                if not info.get("downloadUrl"):
                    manual.append(mod.get("name", info.get("fileName", "?")))
                    continue
                target = _safe_target(inst.path, f"{folder}/{info['fileName']}")
                target.parent.mkdir(parents=True, exist_ok=True)
                progress(tr("Lade {file} ({n}/{total}) …").format(file=info["fileName"], n=n, total=len(files)), n, len(files))
                download(info["downloadUrl"], target)
                kind = next((k for k, v in KINDS.items() if v["folder"] == folder), "mods")
                inst.content[kind].items.append(Mod(
                    file=info["fileName"], name=mod.get("name", info["fileName"]), source="curseforge",
                    project_id=str(mod.get("id", "")), version_id=str(info["id"]),
                    version_name=info.get("displayName", ""), icon_url=(mod.get("logo") or {}).get("thumbnailUrl", ""),
                    url=(mod.get("links") or {}).get("websiteUrl", ""), description=mod.get("summary", ""),
                    category=guess_category([c.get("name", "") for c in mod.get("categories", [])],
                                            inst.content[kind].category_names(), kind),
                ))
        progress(tr("Entpacke Overrides …"), 0, 0)
        _extract_overrides(zf, (manifest.get("overrides") or "overrides",), inst.path)
        _finish_import(inst, progress)
    except Exception:
        shutil.rmtree(inst.path, ignore_errors=True)
        raise
    inst.import_manual = manual  # Mods, die manuell geladen werden müssen
    return inst


def _finish_import(inst: Instance, progress) -> None:
    icon = inst.path / "icon.png"
    if icon.exists():
        inst.icon = "icon.png"
    inst.sync_with_disk()
    progress(tr("Ergänze Mod-Infos …"), 0, 0)
    try:
        _apply_modrinth_metadata(inst)
    except (OSError, ValueError):
        pass
    inst.save()
