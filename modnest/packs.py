"""Fertige Modpacks von Modrinth, CurseForge, Feed The Beast, Technic und ATLauncher.

Jeder Anbieter kann suchen (search), Versionen auflisten (versions) und einen Bauplan erstellen
(plan). Den Bauplan setzt modpack.build_instance in eine Instanz um – für alle Anbieter gleich.
"""
import json
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .i18n import tr
from .modpack import (
    Archive, ManualFile, PackPlan, PlanFile, build_instance, backup_before_update, cf_add_files, cf_sha1,
    plan_curseforge, plan_mrpack,
)
from .sources.base import SourceError, download, session
from .sources.curseforge import API as CF_API, LOADER_NAMES, LOADER_TYPES, RELEASE_TYPES
from .sources.modrinth import API as MR_API

PROVIDERS = {
    "modrinth": "Modrinth",
    "curseforge": "CurseForge",
    "ftb": "Feed The Beast",
    "technic": "Technic",
    "atlauncher": "ATLauncher",
}
PAGE_SIZE = 30
LOADERS = ("fabric", "forge", "neoforge", "quilt")


@dataclass
class PackInfo:
    provider: str
    pack_id: str
    name: str
    author: str = ""
    summary: str = ""
    icon_url: str = ""
    downloads: int = 0
    url: str = ""
    mc_versions: list = field(default_factory=list)
    loaders: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class PackVersion:
    version_id: str
    name: str
    mc_version: str = ""
    loader: str = ""
    date: str = ""                # ISO-Datum
    release_type: str = "release"
    changelog: str = ""
    recommended: bool = False
    extra: dict = field(default_factory=dict)


def _iso(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _get(url: str, **kwargs):
    resp = session.get(url, timeout=kwargs.pop("timeout", 25), **kwargs)
    if resp.status_code == 404:
        raise SourceError(tr("Modpack nicht gefunden."))
    resp.raise_for_status()
    return resp.json()


def _cf_key(settings) -> str:
    key = settings.curseforge_api_key.strip()
    if not key:
        raise SourceError(tr("Für CurseForge wird ein API-Key benötigt.\n"
                             "Hol dir kostenlos einen auf console.curseforge.com und trag ihn in den Einstellungen ein."))
    return key


# --- Modrinth -------------------------------------------------------------------
class ModrinthPacks:
    def search(self, query, offset, mc, loader, settings):
        facets = [["project_type:modpack"]]
        if mc:
            facets.append([f"versions:{mc}"])
        if loader:
            facets.append([f"categories:{loader}"])
        data = _get(f"{MR_API}/search", params={"query": query, "facets": json.dumps(facets), "offset": offset,
                                                 "limit": PAGE_SIZE, "index": "relevance" if query else "downloads"})
        return [PackInfo(
            provider="modrinth", pack_id=h["project_id"], name=h.get("title", ""), author=h.get("author", ""),
            summary=h.get("description", ""), icon_url=h.get("icon_url") or "", downloads=h.get("downloads", 0),
            url=f"https://modrinth.com/modpack/{h.get('slug') or h['project_id']}",
            mc_versions=h.get("versions", []), loaders=[c for c in h.get("categories", []) if c in LOADERS],
        ) for h in data.get("hits", [])]

    def versions(self, pack, settings):
        return [PackVersion(
            version_id=v["id"], name=v.get("version_number") or v.get("name", ""),
            mc_version=(v.get("game_versions") or [""])[0], loader=(v.get("loaders") or [""])[0],
            date=v.get("date_published", ""), release_type=v.get("version_type", "release"),
            changelog=v.get("changelog") or "",
        ) for v in _get(f"{MR_API}/project/{pack.pack_id}/version")]

    def plan(self, pack, version, settings, work: Path, progress):
        v = _get(f"{MR_API}/version/{version.version_id}")
        files = v.get("files", [])
        primary = next((f for f in files if f.get("primary")), files[0] if files else None)
        if not primary:
            raise SourceError(tr("Diese Version hat keine Datei."))
        target = work / "pack.mrpack"
        progress(tr("Lade Modpack {name} …").format(name=pack.name), 0, 0)
        download(primary["url"], target, sha1=(primary.get("hashes") or {}).get("sha1", ""))
        return plan_mrpack(target)


# --- CurseForge -----------------------------------------------------------------
class CurseForgePacks:
    CLASS_ID = 4471

    def search(self, query, offset, mc, loader, settings):
        params = {"gameId": 432, "classId": self.CLASS_ID, "searchFilter": query, "sortField": 2,
                  "sortOrder": "desc", "index": offset, "pageSize": PAGE_SIZE}
        if mc:
            params["gameVersion"] = mc
        if loader in LOADER_TYPES:
            params["modLoaderType"] = LOADER_TYPES[loader]
        data = _get(f"{CF_API}/mods/search", params=params, headers={"x-api-key": _cf_key(settings)})["data"]
        result = []
        for m in data:
            versions = {v for f in m.get("latestFilesIndexes", []) for v in [f.get("gameVersion")] if v}
            result.append(PackInfo(
                provider="curseforge", pack_id=str(m["id"]), name=m.get("name", ""),
                author=((m.get("authors") or [{}])[0]).get("name", ""), summary=m.get("summary", ""),
                icon_url=(m.get("logo") or {}).get("thumbnailUrl", ""), downloads=int(m.get("downloadCount", 0)),
                url=(m.get("links") or {}).get("websiteUrl", ""), mc_versions=sorted(versions, reverse=True),
            ))
        return result

    def versions(self, pack, settings):
        files = _get(f"{CF_API}/mods/{pack.pack_id}/files", params={"pageSize": 50},
                     headers={"x-api-key": _cf_key(settings)})["data"]
        files.sort(key=lambda f: f.get("fileDate", ""), reverse=True)
        result = []
        for f in files:
            gv = f.get("gameVersions", [])
            result.append(PackVersion(
                version_id=str(f["id"]), name=f.get("displayName") or f.get("fileName", ""),
                mc_version=next((v for v in gv if v.lower() not in LOADER_NAMES and v[:1].isdigit()), ""),
                loader=next((v.lower() for v in gv if v.lower() in LOADER_NAMES), ""),
                date=f.get("fileDate", ""), release_type=RELEASE_TYPES.get(f.get("releaseType"), "release"),
                extra={"url": f.get("downloadUrl") or "", "sha1": cf_sha1(f), "file": f.get("fileName", "")},
            ))
        return result

    def plan(self, pack, version, settings, work: Path, progress):
        key = _cf_key(settings)
        url = version.extra.get("url")
        if not url:
            raise SourceError(tr("Der Autor erlaubt keinen Download dieses Modpacks über andere Launcher. "
                                 "Lade die ZIP auf {url} herunter und importiere sie über 📦.").format(url=pack.url))
        target = work / "pack.zip"
        progress(tr("Lade Modpack {name} …").format(name=pack.name), 0, 0)
        download(url, target, sha1=version.extra.get("sha1", ""))
        return plan_curseforge(target, key)


# --- Feed The Beast ---------------------------------------------------------------
class FTBPacks:
    API = "https://api.feed-the-beast.com/v1/modpacks/public/modpack"

    def _pack(self, pack_id) -> PackInfo | None:
        try:
            p = _get(f"{self.API}/{pack_id}")
        except Exception:  # noqa: BLE001 – einzelne kaputte Packs überspringen
            return None
        if p.get("status") != "success" or p.get("private"):
            return None
        art = next((a["url"] for a in p.get("art", []) if a.get("type") == "square"), "")
        versions = p.get("versions", [])
        mcs, loaders = [], []
        for v in versions:
            for t in v.get("targets", []):
                if t.get("type") == "game" and t["version"] not in mcs:
                    mcs.append(t["version"])
                if t.get("type") == "modloader" and t["name"] not in loaders:
                    loaders.append(t["name"])
        return PackInfo(
            provider="ftb", pack_id=str(p["id"]), name=p.get("name", ""),
            author=((p.get("authors") or [{}])[0]).get("name", ""), summary=p.get("synopsis", ""),
            icon_url=art, downloads=int(p.get("installs", 0)),
            url=f"https://www.feed-the-beast.com/modpacks/{p['id']}-{p.get('slug', '')}",
            mc_versions=list(reversed(mcs)), loaders=loaders, extra={"versions": versions},
        )

    def search(self, query, offset, mc, loader, settings):
        if offset:
            return []
        if query:
            ids = _get(f"{self.API}/search/40", params={"term": query}).get("packs", [])
        else:
            ids = _get(f"{self.API}/popular/installs/FTB/40").get("packs", [])
        with ThreadPoolExecutor(8) as pool:
            packs = [p for p in pool.map(self._pack, ids) if p]
        if mc:
            packs = [p for p in packs if mc in p.mc_versions]
        if loader:
            packs = [p for p in packs if loader in p.loaders]
        return packs

    def versions(self, pack, settings):
        result = []
        for v in reversed(pack.extra.get("versions", [])):
            if v.get("private"):
                continue
            targets = {t.get("type"): t for t in v.get("targets", [])}
            result.append(PackVersion(
                version_id=str(v["id"]), name=v.get("name", ""),
                mc_version=(targets.get("game") or {}).get("version", ""),
                loader=(targets.get("modloader") or {}).get("name", ""),
                date=_iso(v.get("updated") or v.get("released")),
                release_type={"release": "release", "beta": "beta", "alpha": "alpha"}.get(v.get("type", "").lower(), "beta"),
            ))
        return result

    def plan(self, pack, version, settings, work: Path, progress):
        progress(tr("Lade Modpack-Infos …"), 0, 0)
        v = _get(f"{self.API}/{pack.pack_id}/{version.version_id}")
        targets = {t.get("type"): t for t in v.get("targets", [])}
        loader = (targets.get("modloader") or {}).get("name", "vanilla")
        plan = PackPlan(name=pack.name, mc_version=(targets.get("game") or {}).get("version", ""),
                        loader=loader if loader in LOADERS else "vanilla",
                        loader_version=(targets.get("modloader") or {}).get("version", ""),
                        icon_url=pack.icon_url, ram_mb=int((v.get("specs") or {}).get("recommended", 0) or 0))
        curse = []
        for f in v.get("files", []):
            if f.get("serveronly"):
                continue
            rel = (f.get("path", "").lstrip("./").rstrip("/") + "/" + f["name"]).lstrip("/")
            if f.get("url"):
                plan.files.append(PlanFile(rel, f["url"], f.get("sha1", "")))
            elif f.get("curseforge"):
                curse.append((int(f["curseforge"]["project"]), int(f["curseforge"]["file"]), rel))
        if curse:
            key = settings.curseforge_api_key.strip()
            if key:
                cf_add_files(plan, [(p, fid) for p, fid, _ in curse], key)
            else:
                for p, fid, rel in curse:
                    plan.manual.append(ManualFile(name=Path(rel).name, filename=Path(rel).name,
                                                  folder=str(Path(rel).parent.as_posix()),
                                                  url=f"https://www.curseforge.com/projects/{p}"))
        return plan


# --- Technic ----------------------------------------------------------------------
class TechnicPacks:
    API = "https://api.technicpack.net"

    def _details(self, slug) -> PackInfo | None:
        try:
            p = _get(f"{self.API}/modpack/{slug}", params={"build": 999})
        except Exception:  # noqa: BLE001
            return None
        if not (p.get("solder") or p.get("url")):
            return None
        return PackInfo(
            provider="technic", pack_id=p["name"], name=p.get("displayName", p["name"]), author=p.get("user", ""),
            summary=re.sub(r"<[^>]+>", "", p.get("description") or "")[:300],
            icon_url=(p.get("icon") or {}).get("url", ""), downloads=int(p.get("installs", 0)),
            url=p.get("platformUrl", ""), mc_versions=[p.get("minecraft", "")],
            extra={"solder": p.get("solder") or "", "zip": p.get("url") or "", "version": p.get("version", "")},
        )

    def search(self, query, offset, mc, loader, settings):
        if offset:
            return []
        if not query:
            query = mc or "tekkit"
        hits = _get(f"{self.API}/search", params={"build": 999, "q": query}).get("modpacks", [])[:24]
        with ThreadPoolExecutor(8) as pool:
            packs = [p for p in pool.map(self._details, [h["slug"] for h in hits]) if p]
        if mc:
            packs = [p for p in packs if mc in p.mc_versions]
        return packs

    def versions(self, pack, settings):
        solder = pack.extra.get("solder")
        if not solder:
            return [PackVersion(version_id=pack.extra.get("version") or "1", name=pack.extra.get("version") or "1",
                                mc_version=pack.mc_versions[0], recommended=True)]
        data = _get(f"{solder.rstrip('/')}/modpack/{pack.pack_id}")
        rec, latest = data.get("recommended"), data.get("latest")
        result = []
        for build in reversed(data.get("builds", [])):
            result.append(PackVersion(version_id=build, name=build, recommended=build == rec,
                                      release_type="release" if build == rec or build != latest else "beta",
                                      mc_version=pack.mc_versions[0] if build == rec else ""))
        # Empfohlene Version nach oben
        result.sort(key=lambda v: not v.recommended)
        return result

    def plan(self, pack, version, settings, work: Path, progress):
        solder = pack.extra.get("solder")
        plan = PackPlan(name=pack.name, mc_version=pack.mc_versions[0], icon_url=pack.icon_url,
                        finalize=_technic_finalize)
        if solder:
            progress(tr("Lade Modpack-Infos …"), 0, 0)
            build = _get(f"{solder.rstrip('/')}/modpack/{pack.pack_id}/{version.version_id}")
            plan.mc_version = build.get("minecraft") or plan.mc_version
            for mod in build.get("mods", []):
                plan.archives.append(Archive(url=mod["url"], md5=mod.get("md5", "")))
        else:
            plan.archives.append(Archive(url=pack.extra["zip"]))
        if plan.mc_version and _version_tuple(plan.mc_version) < (1, 12):
            raise SourceError(tr("Technic-Packs vor Minecraft 1.12 werden leider nicht unterstützt "
                                 "(sie brauchen ein sehr altes Forge)."))
        return plan


def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def _technic_finalize(inst, plan: PackPlan) -> None:
    """Technic-Packs bringen den Loader als bin/modpack.jar mit – Version daraus auslesen."""
    bin_dir = inst.path / "bin"
    version_json = None
    jar = bin_dir / "modpack.jar"
    if jar.is_file():
        try:
            with zipfile.ZipFile(jar) as zf:
                if "version.json" in zf.namelist():
                    version_json = json.loads(zf.read("version.json"))
        except (zipfile.BadZipFile, ValueError, OSError):
            pass
    if version_json is None and (bin_dir / "version.json").is_file():
        version_json = json.loads((bin_dir / "version.json").read_text(encoding="utf-8", errors="replace"))
    vid = (version_json or {}).get("id", "")
    fabric = re.search(r"fabric-loader-([\d.]+)", vid)
    neo = re.search(r"neoforge-([\d.]+(?:-beta)?)", vid, re.I)
    forge = re.search(r"forge-?(?:\d+\.\d+(?:\.\d+)?-)?(\d+(?:\.\d+)+)", vid, re.I)
    if fabric:
        plan.loader, plan.loader_version = "fabric", fabric.group(1)
    elif neo:
        plan.loader, plan.loader_version = "neoforge", neo.group(1)
    elif forge:
        plan.loader, plan.loader_version = "forge", forge.group(1)
    elif any((inst.path / "mods").glob("*.jar")):
        raise SourceError(tr("Der Mod-Loader dieses Technic-Packs konnte nicht erkannt werden."))
    if bin_dir.is_dir():
        import shutil
        shutil.rmtree(bin_dir, ignore_errors=True)


# --- ATLauncher -------------------------------------------------------------------
class ATLauncherPacks:
    API = "https://api.atlauncher.com/v1"
    CDN = "https://download.nodecdn.net/containers/atl"
    _cache: tuple[float, list] = (0.0, [])

    def _all(self) -> list:
        stamp, data = ATLauncherPacks._cache
        if time.time() - stamp > 600 or not data:
            data = _get(f"{self.API}/packs/full/public")["data"]
            ATLauncherPacks._cache = (time.time(), data)
        return data

    def search(self, query, offset, mc, loader, settings):
        q = query.lower()
        packs = []
        for p in self._all():
            versions = p.get("versions") or []
            if not versions:
                continue
            if q and q not in p.get("name", "").lower() and q not in (p.get("description") or "").lower():
                continue
            mcs = list(dict.fromkeys(v.get("minecraft", "") for v in versions))
            if mc and mc not in mcs:
                continue
            packs.append(PackInfo(
                provider="atlauncher", pack_id=p["safeName"], name=p.get("name", ""),
                summary=re.sub(r"\s+", " ", p.get("description") or "")[:300],
                icon_url=f"https://cdn.atlcdn.net/images/packs/{p['safeName'].lower()}.png",
                url=p.get("websiteURL") or f"https://atlauncher.com/pack/{p['safeName']}",
                mc_versions=mcs, extra={"versions": versions, "published": max(v.get("published", 0) for v in versions)},
            ))
        packs.sort(key=lambda p: p.extra["published"], reverse=True)
        return packs[offset:offset + PAGE_SIZE]

    def versions(self, pack, settings):
        return [PackVersion(version_id=v["version"], name=v["version"], mc_version=v.get("minecraft", ""),
                            date=_iso(v.get("published"))) for v in pack.extra.get("versions", [])]

    def plan(self, pack, version, settings, work: Path, progress):
        progress(tr("Lade Modpack-Infos …"), 0, 0)
        base = f"{self.CDN}/packs/{pack.pack_id}/versions/{version.version_id}"
        cfg = _get(f"{base}/Configs.json")
        ld = cfg.get("loader") or {}
        meta = ld.get("metadata") or {}
        loader = ld.get("type", "vanilla") if ld.get("type") in LOADERS else "vanilla"
        loader_version = meta.get("loader") if loader in ("fabric", "quilt") else meta.get("version", "")
        plan = PackPlan(name=pack.name, mc_version=cfg.get("minecraft") or version.mc_version, loader=loader,
                        loader_version=loader_version or "", icon_url=pack.icon_url)
        if (ld and loader == "vanilla") or any(m.get("type") in ("jar", "coremods", "forge") for m in cfg.get("mods", [])):
            raise SourceError(tr("Dieses ATLauncher-Pack nutzt ein altes Format, das ModNest nicht unterstützt. "
                                 "Wähle eine neuere Version oder ein anderes Pack."))
        if cfg.get("configs"):
            plan.archives.append(Archive(url=f"{base}/Configs.zip", sha1=cfg["configs"].get("sha1", "")))
        folders = {"mods": "mods", "resourcepack": "resourcepacks", "shaderpack": "shaderpacks",
                   "dependency": f"mods/{plan.mc_version}"}
        curse = []
        for m in cfg.get("mods", []):
            if m.get("client") is False or (m.get("optional") and not m.get("recommended", True)):
                continue
            mtype = m.get("type", "mods")
            dl = m.get("download")
            url = f"{self.CDN}/{m['url']}" if dl == "server" else m.get("url", "")
            if mtype == "extract":
                dest = {"root": "", "mods": "mods", "config": "config"}.get(m.get("extractTo", "root"), "")
                plan.archives.append(Archive(url=url, md5=m.get("md5", ""), prefix=(m.get("extractFolder") or "").strip("/"),
                                             dest=dest))
                continue
            folder = folders.get(mtype)
            if folder is None:
                continue
            rel = f"{folder}/{m['file']}"
            if dl in ("server", "direct") and url:
                plan.files.append(PlanFile(rel, url, md5=m.get("md5", ""), label=m.get("name", "")))
            elif m.get("curse_id") and m.get("curse_file_id"):
                curse.append((int(m["curse_id"]), int(m["curse_file_id"]), m))
            else:
                plan.manual.append(ManualFile(name=m.get("name", m["file"]), filename=m["file"], folder=folder,
                                              url=m.get("website") or m.get("url", "")))
        if curse:
            key = settings.curseforge_api_key.strip()
            if key:
                cf_add_files(plan, [(p, f) for p, f, _ in curse], key)
            else:
                for _, _, m in curse:
                    plan.manual.append(ManualFile(name=m.get("name", m["file"]), filename=m["file"], folder="mods",
                                                  url=m.get("website", "")))
        return plan


_PROVIDERS = {"modrinth": ModrinthPacks(), "curseforge": CurseForgePacks(), "ftb": FTBPacks(),
              "technic": TechnicPacks(), "atlauncher": ATLauncherPacks()}


def provider(key: str):
    return _PROVIDERS[key]


def _origin(pack: PackInfo, version: PackVersion) -> dict:
    return {"provider": pack.provider, "id": pack.pack_id, "name": pack.name, "version_id": version.version_id,
            "version_name": version.name, "icon_url": pack.icon_url, "url": pack.url, "extra": _small_extra(pack)}


def _small_extra(pack: PackInfo) -> dict:
    """Nur die Infos, die für spätere Updates nötig sind (keine kompletten Versionslisten)."""
    return {k: v for k, v in pack.extra.items() if k in ("solder", "zip")}


def install(pack: PackInfo, version: PackVersion, settings, progress, name: str | None = None):
    """Installiert ein Modpack als neue Instanz."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="modnest-") as tmp:
        plan = _checked(provider(pack.provider).plan(pack, version, settings, Path(tmp), progress), pack)
        return build_instance(plan, settings, progress, name or pack.name, _origin(pack, version))


def _checked(plan: PackPlan, pack: PackInfo) -> PackPlan:
    plan.icon_url = plan.icon_url or pack.icon_url
    if plan.loader == "forge" and plan.mc_version and _version_tuple(plan.mc_version) < (1, 12):
        raise SourceError(tr("Modpacks mit Forge vor Minecraft 1.12 werden leider nicht unterstützt. "
                             "Wähle eine neuere Version des Packs."))
    return plan


def pack_from_instance(inst) -> PackInfo | None:
    """Baut aus der gespeicherten Herkunft wieder ein PackInfo (für Updates)."""
    origin = inst.pack or {}
    if origin.get("provider") not in _PROVIDERS:
        return None
    pack = PackInfo(provider=origin["provider"], pack_id=origin["id"], name=origin.get("name", inst.name),
                    icon_url=origin.get("icon_url", ""), url=origin.get("url", ""),
                    mc_versions=[inst.mc_version], extra=dict(origin.get("extra") or {}))
    if pack.provider in ("ftb", "atlauncher", "technic"):
        fresh = _refresh(pack)
        if fresh:
            pack = fresh
    return pack


def _refresh(pack: PackInfo) -> PackInfo | None:
    if pack.provider == "ftb":
        return FTBPacks()._pack(pack.pack_id)
    if pack.provider == "technic":
        return TechnicPacks()._details(pack.pack_id)
    if pack.provider == "atlauncher":
        for p in ATLauncherPacks()._all():
            if p.get("safeName") == pack.pack_id:
                return PackInfo(provider="atlauncher", pack_id=p["safeName"], name=p.get("name", ""),
                                icon_url=pack.icon_url, url=pack.url,
                                extra={"versions": p.get("versions") or []})
    return None


def check_update(inst, settings) -> tuple | None:
    """(PackInfo, neue PackVersion) wenn es für ein installiertes Modpack ein Update gibt, sonst None."""
    pack = pack_from_instance(inst)
    if pack is None:
        return None
    versions = provider(pack.provider).versions(pack, settings)
    if not versions:
        return None
    current = inst.pack.get("version_id")
    # Nur innerhalb derselben Minecraft-Version aktualisieren (ein Versionssprung kann Welten beschädigen)
    same_mc = [v for v in versions if not v.mc_version or v.mc_version == inst.mc_version]
    versions = same_mc or versions
    if pack.provider == "technic":
        newest = next((v for v in versions if v.recommended), versions[0])
    else:
        stable = [v for v in versions if v.release_type == "release"]
        newest = (stable or versions)[0]
        index = {v.version_id: i for i, v in enumerate(versions)}
        if current in index and index[newest.version_id] > index[current]:
            return None   # installierte Version ist neuer (z.B. Beta)
    if newest.version_id == current:
        return None
    return pack, newest


def update(inst, pack: PackInfo, version: PackVersion, settings, progress):
    """Aktualisiert eine Modpack-Instanz. Vorher wird automatisch ein Backup angelegt."""
    import tempfile
    progress(tr("Sichere Mods und Configs …"), 0, 0)
    backup_before_update(inst, settings)
    with tempfile.TemporaryDirectory(prefix="modnest-") as tmp:
        plan = _checked(provider(pack.provider).plan(pack, version, settings, Path(tmp), progress), pack)
        return build_instance(plan, settings, progress, origin=_origin(pack, version), instance=inst)
