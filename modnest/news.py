"""Minecraft-News aus Mojangs Launcher-Feed und Prüfung auf neue ModNest-Versionen (GitHub)."""
from dataclasses import dataclass

from .config import APP_VERSION
from .sources.base import session

CONTENT = "https://launchercontent.mojang.com"
GITHUB_REPO = "einfachnurflips/modnest-launcher"


@dataclass
class NewsItem:
    title: str
    text: str
    date: str
    image_url: str
    link: str
    tag: str
    content_path: str = ""     # Patch-Notes: werden im Launcher angezeigt


def minecraft_news(limit: int = 8) -> list[NewsItem]:
    """Java-Edition-News und Patch-Notes, neueste zuerst."""
    items: list[NewsItem] = []
    resp = session.get(f"{CONTENT}/v2/news.json", timeout=15)
    resp.raise_for_status()
    for e in resp.json().get("entries", []):
        if "Java" not in e.get("category", ""):
            continue
        img = (e.get("newsPageImage") or e.get("playPageImage") or {}).get("url", "")
        items.append(NewsItem(e.get("title", ""), e.get("text", ""), e.get("date", "")[:10],
                              CONTENT + img if img else "", e.get("readMoreLink", ""), e.get("tag") or "News"))
    try:
        resp = session.get(f"{CONTENT}/v2/javaPatchNotes.json", timeout=15)
        resp.raise_for_status()
        for e in resp.json().get("entries", [])[:3]:
            img = (e.get("image") or {}).get("url", "")
            kind = "Release" if e.get("type") == "release" else "Snapshot"
            items.append(NewsItem(e.get("title", ""), e.get("shortText", ""), e.get("date", "")[:10],
                                  CONTENT + img if img else "", "", kind, e.get("contentPath", "")))
    except (OSError, ValueError):
        pass
    items.sort(key=lambda n: n.date, reverse=True)
    return items[:limit]


def patch_notes_html(content_path: str) -> str:
    resp = session.get(f"{CONTENT}/v2/{content_path}", timeout=15)
    resp.raise_for_status()
    return resp.json().get("body", "")


def _version_tuple(text: str) -> tuple:
    parts = []
    for p in text.lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def launcher_update() -> dict | None:
    """Neuere ModNest-Version auf GitHub (Release oder Tag) – sonst None."""
    resp = session.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        tag = data.get("tag_name", "")
        if tag and _version_tuple(tag) > _version_tuple(APP_VERSION):
            return {"version": tag.lstrip("vV"), "url": data.get("html_url", ""), "notes": data.get("body", "")}
        return None
    resp = session.get(f"https://api.github.com/repos/{GITHUB_REPO}/tags", timeout=10)
    if resp.status_code == 200:
        tags = [t.get("name", "") for t in resp.json()]
        newer = sorted((t for t in tags if _version_tuple(t) > _version_tuple(APP_VERSION)),
                       key=_version_tuple, reverse=True)
        if newer:
            return {"version": newer[0].lstrip("vV"), "url": f"https://github.com/{GITHUB_REPO}/tags", "notes": ""}
    return None
