"""Gemeinsame Typen und HTTP-Helfer für die Mod-Datenbanken."""
from dataclasses import dataclass, field
from pathlib import Path

import requests

from ..config import USER_AGENT

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


class SourceError(Exception):
    """Fehler mit verständlicher Meldung für die Oberfläche."""


@dataclass
class Project:
    source: str
    project_id: str
    title: str
    kind: str = "mods"             # mods | resourcepacks | shaderpacks
    author: str = ""
    description: str = ""
    downloads: int = 0
    icon_url: str = ""
    url: str = ""
    categories: list[str] = field(default_factory=list)


@dataclass
class Release:
    version_id: str
    version_name: str
    filename: str
    download_url: str
    dependencies: list[str] = field(default_factory=list)   # project_ids (Pflicht-Abhängigkeiten)
    release_type: str = "release"                            # release | beta | alpha
    date: str = ""                                           # ISO-Datum
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)


def pick_latest(releases: list[Release]) -> Release:
    """Neueste stabile Version, sonst die neueste überhaupt (Liste ist neueste zuerst)."""
    stable = [r for r in releases if r.release_type == "release"]
    return (stable or releases)[0]


def download(url: str, target: Path, progress=None) -> None:
    tmp = target.with_name(target.name + ".part")
    with session.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(64 * 1024):
                fh.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done, total)
    tmp.replace(target)
