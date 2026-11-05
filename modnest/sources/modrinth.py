"""Modrinth API v2 – https://docs.modrinth.com/api/"""
import json

from .base import Project, Release, SourceError, pick_latest, session
from ..i18n import tr

API = "https://api.modrinth.com/v2"
PROJECT_TYPES = {"mods": "mod", "resourcepacks": "resourcepack", "shaderpacks": "shader"}


def _get(path: str, **params):
    resp = session.get(API + path, params=params, timeout=20)
    if resp.status_code == 404:
        raise SourceError(tr("Projekt auf Modrinth nicht gefunden."))
    resp.raise_for_status()
    return resp.json()


def _project_from_hit(hit: dict, kind: str) -> Project:
    ptype = PROJECT_TYPES[kind]
    return Project(
        source="modrinth",
        project_id=hit.get("project_id") or hit.get("id"),
        title=hit.get("title", ""),
        kind=kind,
        author=hit.get("author", ""),
        description=hit.get("description", ""),
        downloads=hit.get("downloads", 0),
        icon_url=hit.get("icon_url") or "",
        url=f"https://modrinth.com/{ptype}/{hit.get('slug') or hit.get('project_id')}",
        categories=list(hit.get("categories", [])) + list(hit.get("additional_categories", []) or []),
    )


SORTS = {"relevance": "relevance", "downloads": "downloads", "newest": "newest", "updated": "updated"}


def search(query: str, mc_version: str, loader: str, offset: int = 0, limit: int = 30,
           kind: str = "mods", sort: str = "", category: str = "") -> list[Project]:
    facets = [[f"project_type:{PROJECT_TYPES[kind]}"]]
    if category:
        facets.append([f"categories:{category}"])
    if kind == "mods" and loader and loader != "vanilla":
        facets.append([f"categories:{loader}"])
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    data = _get(
        "/search",
        query=query,
        facets=json.dumps(facets),
        index=SORTS.get(sort) or ("relevance" if query else "downloads"),
        offset=offset,
        limit=limit,
    )
    return [_project_from_hit(h, kind) for h in data.get("hits", [])]


def get_project(project_id: str, kind: str = "mods") -> Project:
    data = _get(f"/project/{project_id}")
    data["project_id"] = data["id"]
    kind = {v: k for k, v in PROJECT_TYPES.items()}.get(data.get("project_type"), kind)
    return _project_from_hit(data, kind)


def _release_from_version(v: dict) -> Release:
    files = v.get("files", [])
    if not files:
        raise SourceError(tr("Diese Version hat keine Datei."))
    primary = next((f for f in files if f.get("primary")), files[0])
    deps = [
        d["project_id"]
        for d in v.get("dependencies", [])
        if d.get("dependency_type") == "required" and d.get("project_id")
    ]
    return Release(
        version_id=v["id"],
        version_name=v.get("version_number", "") or v.get("name", ""),
        filename=primary["filename"],
        download_url=primary["url"],
        dependencies=deps,
        release_type=v.get("version_type", "release"),
        date=v.get("date_published", ""),
        game_versions=v.get("game_versions", []),
        loaders=v.get("loaders", []),
        sha1=(primary.get("hashes") or {}).get("sha1", ""),
        changelog=v.get("changelog") or "",
    )


def list_versions(project_id: str, mc_version: str, loader: str, kind: str = "mods") -> list[Release]:
    """Alle Versionen, neueste zuerst. mc_version/loader leer = nicht filtern."""
    params = {}
    if mc_version:
        params["game_versions"] = json.dumps([mc_version])
    if kind == "mods" and loader and loader != "vanilla":
        params["loaders"] = json.dumps([loader])
    versions = _get(f"/project/{project_id}/version", **params)
    result = []
    for v in versions:
        try:
            result.append(_release_from_version(v))
        except SourceError:
            continue
    return result


def resolve(project_id: str, mc_version: str, loader: str, kind: str = "mods") -> Release:
    versions = list_versions(project_id, mc_version, loader, kind)
    if not versions:
        raise SourceError(tr("Keine Version für Minecraft {mc}{loader} verfügbar.").format(
            mc=mc_version, loader=f" ({loader})" if kind == "mods" else ""))
    return pick_latest(versions)


def details(project_id: str) -> dict:
    """Beschreibung, Bilder und Links für die Projektseite."""
    p = _get(f"/project/{project_id}")
    links = {"source": p.get("source_url"), "issues": p.get("issues_url"), "wiki": p.get("wiki_url"),
             "discord": p.get("discord_url")}
    return {
        "body": p.get("body") or p.get("description", ""),
        "format": "markdown",
        "gallery": [(g.get("raw_url") or g["url"], g.get("url"), g.get("title") or "") for g in
                    sorted(p.get("gallery", []), key=lambda g: g.get("ordering", 0))],
        "links": {k: v for k, v in links.items() if v},
        "updated": p.get("updated", ""),
        "followers": p.get("followers", 0),
        "downloads": p.get("downloads", 0),
        "license": (p.get("license") or {}).get("name") or (p.get("license") or {}).get("id", ""),
        "categories": list(p.get("categories", [])),
        "versions": list(p.get("game_versions", []))[-6:],
    }


def categories(kind: str) -> list[str]:
    """Kategorien einer Inhaltsart (ohne Loader/Auflösungen)."""
    ptype = PROJECT_TYPES.get(kind, kind)
    tags = _get("/tag/category")
    return sorted(t["name"] for t in tags if t.get("project_type") == ptype and t.get("header") == "categories")
