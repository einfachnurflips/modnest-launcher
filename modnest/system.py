"""Systeminfos (Arbeitsspeicher) ohne zusätzliche Pakete."""
import ctypes
import sys
from .i18n import tr


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def total_ram_mb() -> int:
    """Installierter Arbeitsspeicher in MB (Fallback 8 GB)."""
    if sys.platform == "win32":
        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys // (1024 * 1024))
    return 8192


def ram_rating(ram_mb: int, total_mb: int) -> tuple[str, str]:
    """(Farbe, Hinweis) für eine RAM-Zuweisung."""
    if ram_mb < 2048:
        return "#ef4444", tr("Zu wenig – Minecraft mit Mods wird ruckeln oder abstürzen.")
    if ram_mb > total_mb - 2048:
        return "#ef4444", tr("Zu viel – Windows braucht selbst noch Speicher, das kann alles verlangsamen.")
    if ram_mb < 4096:
        return "#f59e0b", tr("Reicht für Vanilla und kleine Modpacks.")
    if ram_mb > 12288:
        return "#f59e0b", tr("Mehr als 12 GB bringt meist nichts und kann Ruckler (Garbage Collection) verursachen.")
    return "#22c55e", tr("Gute Wahl für die meisten Modpacks.")
