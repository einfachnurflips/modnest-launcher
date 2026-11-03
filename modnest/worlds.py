"""Welten und Server einer Instanz auslesen sowie Server-Status abfragen (Server List Ping)."""
import base64
import json
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from .nbt import read_nbt
from .i18n import tr


@dataclass
class World:
    instance_path: Path
    folder: str
    name: str
    last_played: float          # Unix-Zeit
    game_mode: str = ""
    icon: Path | None = None

    @property
    def path(self) -> Path:
        return self.instance_path / "saves" / self.folder


@dataclass
class Server:
    name: str
    address: str
    icon_png: bytes | None = None

    @property
    def host_port(self) -> tuple[str, int]:
        host, _, port = self.address.strip().rpartition(":")
        if host and port.isdigit() and not host.endswith("]"):
            return host, int(port)
        return self.address.strip(), 25565


@dataclass
class ServerStatus:
    online: bool
    players: int = 0
    max_players: int = 0
    motd: str = ""
    version: str = ""
    ping_ms: int = 0
    favicon: bytes | None = None


GAME_MODES = {0: tr("Überleben"), 1: tr("Kreativ"), 2: tr("Abenteuer"), 3: tr("Zuschauer")}


def list_worlds(instance_path: Path) -> list[World]:
    saves = instance_path / "saves"
    worlds = []
    if not saves.is_dir():
        return worlds
    for folder in saves.iterdir():
        level = folder / "level.dat"
        if not level.is_file():
            continue
        name, last, mode = folder.name, level.stat().st_mtime, ""
        try:
            data = read_nbt(level).get("Data", {})
            name = data.get("LevelName") or folder.name
            if data.get("LastPlayed"):
                last = data["LastPlayed"] / 1000
            if data.get("hardcore"):
                mode = tr("Hardcore")
            else:
                mode = GAME_MODES.get(data.get("GameType", 0), "")
        except (OSError, ValueError, KeyError):
            pass
        icon = folder / "icon.png"
        worlds.append(World(instance_path, folder.name, name, last, mode, icon if icon.exists() else None))
    worlds.sort(key=lambda w: w.last_played, reverse=True)
    return worlds


def list_servers(instance_path: Path) -> list[Server]:
    path = instance_path / "servers.dat"
    if not path.exists():
        return []
    try:
        data = read_nbt(path)
    except (OSError, ValueError):
        return []
    servers = []
    for entry in data.get("servers", []):
        if not isinstance(entry, dict) or not entry.get("ip"):
            continue
        icon = None
        if entry.get("icon"):
            try:
                icon = base64.b64decode(entry["icon"])
            except ValueError:
                icon = None
        servers.append(Server(entry.get("name") or entry["ip"], entry["ip"], icon))
    return servers


# --- Server List Ping ----------------------------------------------------------
def _varint(value: int) -> bytes:
    out = b""
    value &= 0xFFFFFFFF
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


def _read_varint(sock: socket.socket) -> int:
    result = 0
    for i in range(5):
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("Verbindung geschlossen")
        result |= (byte[0] & 0x7F) << (7 * i)
        if not byte[0] & 0x80:
            return result
    raise ValueError("VarInt zu lang")


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Verbindung geschlossen")
        buf += chunk
    return buf


def _motd_text(desc) -> str:
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        return desc.get("text", "") + "".join(_motd_text(e) for e in desc.get("extra", []))
    if isinstance(desc, list):
        return "".join(_motd_text(e) for e in desc)
    return ""


def ping(address: str, timeout: float = 4.0) -> ServerStatus:
    """Fragt den Status eines Java-Servers ab (Spieler online, MOTD, Ping)."""
    host, port = Server("", address).host_port
    try:
        start = time.perf_counter()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            host_bytes = host.encode()
            handshake = (b"\x00" + _varint(767) + _varint(len(host_bytes)) + host_bytes
                         + struct.pack(">H", port) + _varint(1))
            sock.sendall(_varint(len(handshake)) + handshake + b"\x01\x00")
            _read_varint(sock)                 # Paketlänge
            if _read_varint(sock) != 0:        # Paket-ID
                return ServerStatus(False)
            payload = _recv_exact(sock, _read_varint(sock))
            latency = int((time.perf_counter() - start) * 1000)
        data = json.loads(payload.decode("utf-8", errors="replace"))
    except (OSError, ValueError, ConnectionError):
        return ServerStatus(False)
    players = data.get("players") or {}
    favicon = None
    fav = data.get("favicon") or ""
    if fav.startswith("data:image/png;base64,"):
        try:
            favicon = base64.b64decode(fav.split(",", 1)[1])
        except ValueError:
            favicon = None
    motd = " ".join(_motd_text(data.get("description")).split())
    for code in "0123456789abcdefklmnor":
        motd = motd.replace("§" + code, "")
    return ServerStatus(True, int(players.get("online", 0)), int(players.get("max", 0)), motd,
                        (data.get("version") or {}).get("name", ""), latency, favicon)
