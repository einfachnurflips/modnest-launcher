from types import SimpleNamespace

from . import modrinth
from .base import Project, Release, SourceError
from .curseforge import CurseForge

SOURCES = {"modrinth": "Modrinth", "curseforge": "CurseForge"}


def get_source(name: str, settings):
    """Liefert ein Objekt mit search(), get_project(), list_versions() und resolve()."""
    if name == "curseforge":
        return CurseForge(settings.curseforge_api_key.strip())
    return SimpleNamespace(search=modrinth.search, get_project=modrinth.get_project,
                           list_versions=modrinth.list_versions, resolve=modrinth.resolve,
                           details=modrinth.details, categories=modrinth.categories)


__all__ = ["Project", "Release", "SourceError", "SOURCES", "get_source"]
