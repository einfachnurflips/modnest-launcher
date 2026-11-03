"""Gemeinsame Typen und HTTP-Helfer für die Mod-Datenbanken."""
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

from ..config import USER_AGENT
from ..i18n import tr

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT
session.mount("https://", HTTPAdapter(pool_connections=16, pool_maxsize=16))


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
    sha1: str = ""                                           # Prüfsumme (falls die Quelle sie liefert)
    changelog: str = ""


def pick_latest(releases: list[Release]) -> Release:
    """Neueste stabile Version, sonst die neueste überhaupt (Liste ist neueste zuerst)."""
    stable = [r for r in releases if r.release_type == "release"]
    return (stable or releases)[0]


class ChecksumError(SourceError):
    pass


def _download_once(url: str, target: Path, progress, sha1: str, md5: str = "") -> None:
    tmp = target.with_name(target.name + ".part")
    expected = (sha1 or md5).lower()
    digest = hashlib.sha1() if sha1 or not md5 else hashlib.md5()
    try:
        with session.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(64 * 1024):
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done, total)
        if expected and digest.hexdigest().lower() != expected:
            raise ChecksumError(tr("Prüfsumme von {file} stimmt nicht.").format(file=target.name))
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)


def download(url: str, target: Path, progress=None, sha1: str = "", retries: int = 3, md5: str = "") -> None:
    """Lädt eine Datei herunter, prüft optional die SHA-1-Prüfsumme und versucht es bei Fehlern erneut."""
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        try:
            _download_once(url, target, progress, sha1, md5)
            return
        except (requests.RequestException, ChecksumError, OSError):
            if attempt == retries:
                raise
            time.sleep(attempt)


@dataclass
class DownloadJob:
    url: str
    target: Path
    sha1: str = ""
    label: str = ""
    md5: str = ""


def download_many(jobs: list[DownloadJob], progress=None, workers: int = 6) -> None:
    """Lädt mehrere Dateien parallel. progress(text, fertig, gesamt). Bricht beim ersten Fehler ab."""
    if not jobs:
        return
    total, finished = len(jobs), 0
    lock = threading.Lock()

    def run(job: DownloadJob):
        if job.sha1 and job.target.is_file() and _sha1_file(job.target) == job.sha1.lower():
            return job  # schon vorhanden und korrekt
        download(job.url, job.target, sha1=job.sha1, md5=job.md5)
        return job

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, j) for j in jobs]
        try:
            for fut in as_completed(futures):
                job = fut.result()
                with lock:
                    finished += 1
                if progress:
                    progress(tr("Lade Dateien ({n}/{total}) – {file}").format(
                        n=finished, total=total, file=job.label or job.target.name), finished, total)
        except BaseException as exc:
            for f in futures:
                f.cancel()
            if isinstance(exc, requests.RequestException):
                raise SourceError(tr("Download fehlgeschlagen: {e}").format(e=exc)) from exc
            raise


def _sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()
