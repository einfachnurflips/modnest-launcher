"""Server-Benachrichtigungen: pro Server einstellbar, ob ModNest Bescheid sagt, wenn der Server online kommt,
jemand draufkommt oder bestimmte Spieler online sind. Es wird nur der normale Server-Status abgefragt
(wie in der Serverliste im Spiel) – niemand sonst sieht etwas davon."""
from .i18n import tr

INTERVAL_S = 60


def _key(address: str) -> str:
    return address.strip().lower()


def watches(settings) -> dict:
    """Adresse → {name, online, anyone, players: [...]}"""
    data = settings.extra.get("server_watch")
    return data if isinstance(data, dict) else {}


def get(settings, address: str) -> dict:
    return watches(settings).get(_key(address), {})


def is_watched(settings, address: str) -> bool:
    cfg = get(settings, address)
    return bool(cfg.get("online") or cfg.get("anyone") or cfg.get("players"))


def set_watch(settings, address: str, name: str, online: bool, anyone: bool, players: list[str]) -> None:
    data = dict(watches(settings))
    players = [p.strip() for p in players if p.strip()]
    if online or anyone or players:
        data[_key(address)] = {"address": address.strip(), "name": name, "online": online, "anyone": anyone,
                               "players": players}
    else:
        data.pop(_key(address), None)
    settings.extra["server_watch"] = data
    settings.save()


def parse_players(text: str) -> list[str]:
    seen, out = set(), []
    for part in text.replace(";", ",").replace("\n", ",").split(","):
        name = part.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


class Tracker:
    """Merkt sich den letzten Stand pro Server und liefert Meldungen bei Änderungen."""

    def __init__(self):
        self.state: dict[str, tuple[bool, int, set]] = {}

    def update(self, cfg: dict, status) -> list[str]:
        key = _key(cfg.get("address", ""))
        name = cfg.get("name") or cfg.get("address", "")
        names = {n.lower(): n for n in getattr(status, "sample", []) or []} if status.online else {}
        prev = self.state.get(key)
        self.state[key] = (status.online, status.players if status.online else 0, set(names))
        msgs = []
        if prev is not None:
            was_online, was_count, _ = prev
            if cfg.get("online") and status.online and not was_online:
                msgs.append(tr("🟢 {server} ist wieder online.").format(server=name))
            if cfg.get("anyone") and status.online and status.players > 0 and was_count == 0:
                msgs.append(tr("👥 Auf {server} ist jetzt jemand online ({n}).").format(server=name, n=status.players))
        before = prev[2] if prev is not None else set()
        joined = [names[p.lower()] for p in cfg.get("players", []) if p.lower() in names and p.lower() not in before]
        if joined:
            msgs.append(tr("👤 {players} ist/sind auf {server} online.").format(players=", ".join(joined), server=name))
        return msgs
