"""Löschen über den Windows-Papierkorb, damit ein Fehlklick nicht endgültig ist."""
import ctypes
import shutil
import sys
from ctypes import wintypes
from pathlib import Path

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def move_to_trash(path: Path) -> None:
    """Verschiebt Datei/Ordner in den Papierkorb; klappt das nicht, wird endgültig gelöscht."""
    path = Path(path)
    if not path.exists():
        return
    if sys.platform == "win32":
        op = _SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = str(path.resolve()) + "\0"   # Liste muss doppelt nullterminiert sein
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        try:
            if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not path.exists():
                return
        except OSError:
            pass
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
