"""Spielzeit-Statistik: jede Spielrunde wird mit Instanz, Startzeit und Dauer festgehalten."""
import json
import time
from datetime import date, datetime, timedelta

from .config import data_dir

MAX_SESSIONS = 5000


def _path():
    return data_dir() / "playtime.json"


def sessions() -> list[dict]:
    """[{folder, name, start, seconds}] – älteste zuerst."""
    try:
        items = json.loads(_path().read_text(encoding="utf-8")).get("sessions", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [s for s in items if isinstance(s, dict) and s.get("seconds", 0) > 0]


def record(instance, start: float, seconds: int) -> None:
    if seconds < 30:              # Fehlstarts nicht mitzählen
        return
    items = sessions()
    items.append({"folder": instance.path.name, "name": instance.name, "start": start, "seconds": int(seconds)})
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps({"sessions": items[-MAX_SESSIONS:]}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_path())


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly(weeks: int = 12, now: float | None = None) -> list[tuple[date, int]]:
    """Spielzeit pro Kalenderwoche (Montag bis Sonntag), älteste zuerst."""
    this_week = week_start(datetime.fromtimestamp(now or time.time()).date())
    starts = [this_week - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    totals = {s: 0 for s in starts}
    for s in sessions():
        ws = week_start(datetime.fromtimestamp(s["start"]).date())
        if ws in totals:
            totals[ws] += s["seconds"]
    return [(s, totals[s]) for s in starts]


def since(days: int, now: float | None = None) -> int:
    limit = (now or time.time()) - days * 86400
    return sum(s["seconds"] for s in sessions() if s["start"] >= limit)


def this_week(now: float | None = None) -> int:
    return weekly(1, now)[0][1]


def per_instance(days: int, now: float | None = None) -> dict[str, int]:
    """Ordnername → Sekunden in den letzten <days> Tagen."""
    limit = (now or time.time()) - days * 86400
    out: dict[str, int] = {}
    for s in sessions():
        if s["start"] >= limit:
            out[s["folder"]] = out.get(s["folder"], 0) + s["seconds"]
    return out


def streak(now: float | None = None) -> int:
    """Wie viele Tage am Stück (bis heute oder gestern) gespielt wurde."""
    days = {datetime.fromtimestamp(s["start"]).date() for s in sessions()}
    day = datetime.fromtimestamp(now or time.time()).date()
    if day not in days:
        day -= timedelta(days=1)
    n = 0
    while day in days:
        n += 1
        day -= timedelta(days=1)
    return n
