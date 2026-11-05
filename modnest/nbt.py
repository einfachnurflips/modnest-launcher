"""Minimaler NBT-Leser für level.dat (gzip) und servers.dat (unkomprimiert)."""
import gzip
import struct
from pathlib import Path


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        chunk = self.data[self.pos:self.pos + n]
        if len(chunk) != n:
            raise ValueError("NBT-Daten unvollständig")
        self.pos += n
        return chunk

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(">" + fmt, self.take(size))[0]

    def string(self) -> str:
        return self.take(self.unpack("H")).decode("utf-8", errors="replace")

    def payload(self, tag: int):
        if tag == 1:
            return self.unpack("b")
        if tag == 2:
            return self.unpack("h")
        if tag == 3:
            return self.unpack("i")
        if tag == 4:
            return self.unpack("q")
        if tag == 5:
            return self.unpack("f")
        if tag == 6:
            return self.unpack("d")
        if tag == 7:
            return self.take(self.unpack("i"))
        if tag == 8:
            return self.string()
        if tag == 9:
            inner = self.unpack("b")
            return [self.payload(inner) for _ in range(self.unpack("i"))]
        if tag == 10:
            result = {}
            while True:
                inner = self.unpack("b")
                if inner == 0:
                    return result
                name = self.string()
                result[name] = self.payload(inner)
        if tag == 11:
            n = self.unpack("i")
            return list(struct.unpack(f">{n}i", self.take(4 * n)))
        if tag == 12:
            n = self.unpack("i")
            return list(struct.unpack(f">{n}q", self.take(8 * n)))
        raise ValueError(f"Unbekannter NBT-Tag {tag}")


def read_nbt(path: Path) -> dict:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    reader = _Reader(data)
    tag = reader.unpack("b")
    if tag != 10:
        raise ValueError("Keine NBT-Datei")
    reader.string()
    return reader.payload(10)


# --- Schreiben (nur was servers.dat braucht) ------------------------------------------
def _w_string(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def write_servers(path: Path, servers: list[dict]) -> None:
    """Schreibt servers.dat. servers: [{name, ip, icon (Base64, optional), acceptTextures (0/1, optional)}]."""
    out = bytearray(b"\x0a" + _w_string(""))
    out += b"\x09" + _w_string("servers") + b"\x0a" + struct.pack(">i", len(servers))
    for s in servers:
        for key in ("name", "ip", "icon"):
            if s.get(key):
                out += b"\x08" + _w_string(key) + _w_string(str(s[key]))
        for key in ("acceptTextures", "hidden"):
            if key in s and s[key] is not None:
                out += b"\x01" + _w_string(key) + struct.pack(">b", int(s[key]))
        out += b"\x00"
    out += b"\x00"
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(bytes(out))
    tmp.replace(path)
