"""Discord-Status („Spielt Mein Modpack – Fabric 1.21“) über die lokale Discord-Schnittstelle.

Braucht eine Discord-Anwendungs-ID (kostenlos auf discord.com/developers/applications).
Läuft Discord nicht, passiert einfach nichts.
"""
import json
import os
import struct
import threading
import time
import uuid

_lock = threading.Lock()
_pipe = None
_client_id = ""


def _connect(client_id: str):
    for i in range(10):
        try:
            pipe = open(rf"\\?\pipe\discord-ipc-{i}", "r+b", buffering=0)
        except OSError:
            continue
        try:
            _send(pipe, 0, {"v": 1, "client_id": client_id})
            _recv(pipe)
            return pipe
        except OSError:
            pipe.close()
    return None


def _send(pipe, op: int, payload: dict) -> None:
    data = json.dumps(payload).encode()
    pipe.write(struct.pack("<II", op, len(data)) + data)


def _recv(pipe) -> dict:
    header = pipe.read(8)
    if len(header) < 8:
        raise OSError("Discord hat die Verbindung geschlossen")
    _, length = struct.unpack("<II", header)
    return json.loads(pipe.read(length) or b"{}")


def _set(client_id: str, activity: dict | None) -> None:
    global _pipe, _client_id
    with _lock:
        for attempt in range(2):
            try:
                if _pipe is None or _client_id != client_id:
                    if _pipe is not None:
                        _pipe.close()
                    _pipe, _client_id = _connect(client_id), client_id
                if _pipe is None:
                    return
                _send(_pipe, 1, {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid(), "activity": activity},
                                 "nonce": str(uuid.uuid4())})
                _recv(_pipe)
                return
            except (OSError, ValueError):
                try:
                    if _pipe is not None:
                        _pipe.close()
                except OSError:
                    pass
                _pipe = None


def set_playing(client_id: str, instance_name: str, details: str, target: str = "") -> None:
    """Zeigt „Spielt …“ in Discord an (läuft im Hintergrund)."""
    if not client_id:
        return
    activity = {
        "details": instance_name[:128],
        "state": (f"{details} · {target}" if target else details)[:128],
        "timestamps": {"start": int(time.time())},
        "assets": {"large_image": "logo", "large_text": "ModNest Launcher"},
    }
    threading.Thread(target=_set, args=(client_id, activity), daemon=True).start()


def clear(client_id: str) -> None:
    if client_id:
        threading.Thread(target=_set, args=(client_id, None), daemon=True).start()
