"""CurseForge Core API – https://docs.curseforge.com/rest-api/

Benötigt einen eigenen API-Key von https://console.curseforge.com (kostenlos).
"""
from .base import Project, Release, SourceError, pick_latest, session

API = "https://api.curseforge.com/v1"
GAME_MINECRAFT = 432
CLASS_IDS = {"mods": 6, "resourcepacks": 12, "shaderpacks": 6552}
LOADER_TYPES = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
LOADER_NAMES = {"forge", "fabric", "quilt", "neoforge"}
RELEASE_TYPES = {1: "release", 2: "beta", 3: "alpha"}
RELATION_REQUIRED = 3


class CurseForge:
    def __init__(self, api_key: str):
        if not api_key:
            raise SourceError(
                "Für CurseForge wird ein API-Key benötigt.\n"
                "Hol dir kostenlos einen auf console.curseforge.com und trag ihn in den Einstellungen ein."
            )
        self.api_key = api_key

    def _get(self, path: str, **params):
        resp = session.get(API + path, params=params, headers={"x-api-key": self.api_key}, timeout=20)
        if resp.status_code == 403:
            raise SourceError("CurseForge hat den API-Key abgelehnt (403). Bitte in den Einstellungen prüfen.")
        if resp.status_code == 404:
            raise SourceError("Projekt auf CurseForge nicht gefunden.")
        resp.raise_for_status()
        return resp.json()["data"]

    @staticmethod
    def _project(mod: dict, kind: str) -> Project:
        authors = mod.get("authors") or [{}]
        by_class = {v: k for k, v in CLASS_IDS.items()}
        return Project(
            source="curseforge",
            project_id=str(mod["id"]),
            title=mod.get("name", ""),
            kind=by_class.get(mod.get("classId"), kind),
            author=authors[0].get("name", ""),
            description=mod.get("summary", ""),
            downloads=int(mod.get("downloadCount", 0)),
            icon_url=(mod.get("logo") or {}).get("thumbnailUrl", ""),
            url=(mod.get("links") or {}).get("websiteUrl", ""),
            categories=[c.get("name", "") for c in mod.get("categories", [])],
        )

    def search(self, query: str, mc_version: str, loader: str, offset: int = 0, limit: int = 30,
               kind: str = "mods") -> list[Project]:
        params = {
            "gameId": GAME_MINECRAFT,
            "classId": CLASS_IDS[kind],
            "searchFilter": query,
            "sortField": 2,          # Popularität
            "sortOrder": "desc",
            "index": offset,
            "pageSize": limit,
        }
        if mc_version:
            params["gameVersion"] = mc_version
        if kind == "mods" and loader in LOADER_TYPES:
            params["modLoaderType"] = LOADER_TYPES[loader]
        return [self._project(m, kind) for m in self._get("/mods/search", **params)]

    def get_project(self, project_id: str, kind: str = "mods") -> Project:
        return self._project(self._get(f"/mods/{project_id}"), kind)

    def list_versions(self, project_id: str, mc_version: str, loader: str, kind: str = "mods") -> list[Release]:
        params = {"pageSize": 50}
        if mc_version:
            params["gameVersion"] = mc_version
        if kind == "mods" and loader in LOADER_TYPES:
            params["modLoaderType"] = LOADER_TYPES[loader]
        files = self._get(f"/mods/{project_id}/files", **params)
        files.sort(key=lambda f: f.get("fileDate", ""), reverse=True)
        result = []
        for f in files:
            versions = f.get("gameVersions", [])
            result.append(Release(
                version_id=str(f["id"]),
                version_name=f.get("displayName", "") or f.get("fileName", ""),
                filename=f["fileName"],
                download_url=f.get("downloadUrl") or "",
                dependencies=[str(d["modId"]) for d in f.get("dependencies", [])
                              if d.get("relationType") == RELATION_REQUIRED],
                release_type=RELEASE_TYPES.get(f.get("releaseType"), "release"),
                date=f.get("fileDate", ""),
                game_versions=[v for v in versions if v.lower() not in LOADER_NAMES],
                loaders=[v.lower() for v in versions if v.lower() in LOADER_NAMES],
            ))
        return result

    def resolve(self, project_id: str, mc_version: str, loader: str, kind: str = "mods") -> Release:
        versions = self.list_versions(project_id, mc_version, loader, kind)
        if not versions:
            raise SourceError(f"Keine Datei für Minecraft {mc_version}"
                              + (f" ({loader})" if kind == "mods" else "") + " verfügbar.")
        return pick_latest(versions)
