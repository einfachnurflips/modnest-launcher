"""Installiert Mods, Texturepacks und Shader (Mods inklusive Pflicht-Abhängigkeiten) in eine Instanz."""
import re

from .categorize import guess_category
from .instances import Instance, Mod
from .sources import Project, Release, SourceError, get_source
from .sources.base import download


def _safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def install_project(instance: Instance, project: Project, settings, category: str | None, progress,
                    release: Release | None = None) -> list[str]:
    """Lädt das Projekt (und bei Mods die Abhängigkeiten) herunter. Gibt die installierten Namen zurück.

    category=None bedeutet: automatisch anhand der Quell-Kategorien einordnen.
    release=None bedeutet: neueste passende Version; sonst genau diese Version.
    progress(text, value, maximum) wird aus dem Worker-Thread aufgerufen.
    """
    kind = project.kind
    if kind == "mods" and instance.loader == "vanilla":
        raise SourceError("Vanilla-Instanzen unterstützen keine Mods. Erstelle eine Instanz mit Fabric, Forge o.ä.")
    content = instance.content[kind]
    source = get_source(project.source, settings)
    installed: list[str] = []
    visited: set[str] = set()

    def install(proj: Project, cat: str | None, is_dependency: bool, chosen: Release | None):
        if proj.project_id in visited:
            return
        visited.add(proj.project_id)
        if is_dependency and content.find_project(proj.source, proj.project_id):
            return  # Abhängigkeit schon vorhanden
        rel = chosen
        if rel is None:
            progress(f"Suche passende Version von {proj.title} …", 0, 0)
            rel = source.resolve(proj.project_id, instance.mc_version, instance.loader, kind)
        if not rel.download_url:
            raise SourceError(
                f"Der Autor von {proj.title} erlaubt keine Downloads über Drittanbieter-Launcher.\n"
                "Bitte lade die Datei manuell von der Webseite herunter und lege sie in den passenden Ordner."
            )
        filename = _safe_filename(rel.filename)
        progress(f"Lade {filename} …", 0, 100)
        download(rel.download_url, content.folder / filename,
                 lambda done, total: progress(f"Lade {filename} …", done * 100 // total, 100))
        item = Mod(
            file=filename,
            name=proj.title,
            source=proj.source,
            project_id=proj.project_id,
            version_id=rel.version_id,
            version_name=rel.version_name,
            category=cat or guess_category(proj.categories, content.category_names(), kind),
            icon_url=proj.icon_url,
            url=proj.url,
            description=proj.description,
            pinned=chosen is not None,
        )
        content.add(item)
        installed.append(proj.title)
        if kind != "mods":
            return
        for dep_id in rel.dependencies:
            if dep_id in visited or content.find_project(proj.source, dep_id):
                continue
            try:
                install(source.get_project(dep_id, kind), None, True, None)
            except SourceError as exc:
                raise SourceError(f"Abhängigkeit von {proj.title} konnte nicht installiert werden:\n{exc}") from exc

    try:
        install(project, category, False, release)
    finally:
        instance.save()
    return installed


def project_from_item(item: Mod, kind: str) -> Project:
    """Baut aus einem installierten Eintrag wieder ein Project (für Versionswechsel)."""
    return Project(source=item.source, project_id=item.project_id, title=item.name, kind=kind,
                   description=item.description, icon_url=item.icon_url, url=item.url)
