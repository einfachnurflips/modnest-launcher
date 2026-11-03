"""Prüft installierte Mods, Texturepacks und Shader auf neuere Versionen."""
import hashlib
from dataclasses import dataclass

from .instances import KINDS, Instance, Mod
from .sources import Release, SourceError, get_source
from .sources.base import pick_latest, session
from .sources.modrinth import API as MODRINTH_API, _release_from_version


@dataclass
class Update:
    kind: str
    item: Mod
    release: Release


def _sha1(path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def check_updates(instance: Instance, settings) -> list[Update]:
    """Findet Updates. Mit 📌 festgelegte Versionen werden übersprungen."""
    updates: list[Update] = []
    for kind in KINDS:
        content = instance.content[kind]
        # Mods eines fertigen Modpacks werden über das Modpack aktualisiert, nicht einzeln
        pack_files = set((instance.pack or {}).get("files", []))
        folder = KINDS[kind]["folder"]
        candidates = [m for m in content.items if m.project_id and m.source != "local" and not m.pinned
                      and f"{folder}/{m.file}" not in pack_files]
        # Modrinth: alle Dateien in einer Anfrage über ihre SHA1-Prüfsumme
        modrinth_items = {}
        for m in candidates:
            if m.source == "modrinth":
                path = content.folder / m.disk_name
                if path.is_file():
                    modrinth_items[_sha1(path)] = m
        if modrinth_items:
            body = {"hashes": list(modrinth_items), "algorithm": "sha1", "game_versions": [instance.mc_version]}
            if kind == "mods" and instance.loader != "vanilla":
                body["loaders"] = [instance.loader]
            resp = session.post(f"{MODRINTH_API}/version_files/update", json=body, timeout=30)
            if resp.ok:
                for sha, version in resp.json().items():
                    m = modrinth_items.get(sha)
                    if not m or version.get("id") == m.version_id:
                        continue
                    try:
                        release = _release_from_version(version)
                        if release.release_type != "release":
                            # Neueste ist Beta/Alpha – nur die neueste stabile Version anbieten, falls neuer
                            versions = get_source("modrinth", settings).list_versions(
                                m.project_id, instance.mc_version, instance.loader, kind)
                            stable = next((v for v in versions if v.release_type == "release"), None)
                            current = next((v for v in versions if v.version_id == m.version_id), None)
                            if stable is None or stable.version_id == m.version_id:
                                continue
                            if current is not None and current.date >= stable.date:
                                continue
                            release = stable
                        updates.append(Update(kind, m, release))
                    except (SourceError, OSError):
                        pass
        # CurseForge: pro Projekt (nur mit API-Key)
        cf_items = [m for m in candidates if m.source == "curseforge"]
        if cf_items and settings.curseforge_api_key.strip():
            cf = get_source("curseforge", settings)
            for m in cf_items:
                try:
                    versions = cf.list_versions(m.project_id, instance.mc_version, instance.loader, kind)
                except (SourceError, OSError):
                    continue
                if versions:
                    latest = pick_latest(versions)
                    if latest.version_id != m.version_id:
                        current = next((v for v in versions if v.version_id == m.version_id), None)
                        if current is None or latest.date > current.date:
                            updates.append(Update(kind, m, latest))
    return updates
