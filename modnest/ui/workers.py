"""Hintergrund-Aufgaben (Netzwerk, Downloads), damit die Oberfläche nicht einfriert."""
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..config import USER_AGENT
from ..sources import SourceError


class _Signals(QObject):
    done = Signal(object)
    error = Signal(str)
    progress = Signal(object, int, int)


class _Task(QRunnable):
    def __init__(self, fn, signals: _Signals, with_progress: bool):
        super().__init__()
        self.fn = fn
        self.signals = signals
        self.with_progress = with_progress

    def _emit(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            pass  # Launcher wurde geschlossen, während die Aufgabe noch lief

    def run(self):
        try:
            if self.with_progress:
                result = self.fn(lambda text, value, maximum: self._emit(self.signals.progress, text, value, maximum))
            else:
                result = self.fn()
        except SourceError as exc:
            self._emit(self.signals.error, str(exc))
        except Exception as exc:  # noqa: BLE001 – alles an die Oberfläche melden
            traceback.print_exc()
            self._emit(self.signals.error, f"{type(exc).__name__}: {exc}")
        else:
            self._emit(self.signals.done, result)


_alive: set[_Signals] = set()


def run_task(fn, on_done=None, on_error=None, on_progress=None):
    """Führt fn im Thread-Pool aus. Mit on_progress bekommt fn eine progress(text, value, max)-Funktion."""
    signals = _Signals()
    _alive.add(signals)

    def finish(*_):
        _alive.discard(signals)

    if on_done:
        signals.done.connect(on_done)
    if on_error:
        signals.error.connect(on_error)
    if on_progress:
        signals.progress.connect(on_progress)
    signals.done.connect(finish)
    signals.error.connect(finish)
    QThreadPool.globalInstance().start(_Task(fn, signals, on_progress is not None))


class IconLoader(QObject):
    """Lädt Mod-Icons asynchron und cached sie im Speicher."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._net = QNetworkAccessManager(self)
        self._cache: dict[str, QPixmap] = {}
        self._waiting: dict[str, list] = {}

    def load(self, url: str, callback) -> None:
        if not url:
            return
        if url in self._cache:
            callback(self._cache[url])
            return
        if url in self._waiting:
            self._waiting[url].append(callback)
            return
        self._waiting[url] = [callback]
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", USER_AGENT.encode())
        reply = self._net.get(req)
        reply.finished.connect(lambda: self._finished(url, reply))

    def _finished(self, url: str, reply: QNetworkReply) -> None:
        callbacks = self._waiting.pop(url, [])
        pix = QPixmap()
        if reply.error() == QNetworkReply.NetworkError.NoError:
            pix.loadFromData(reply.readAll())
        reply.deleteLater()
        if pix.isNull():
            return
        self._cache[url] = pix
        for cb in callbacks:
            try:
                cb(pix)
            except RuntimeError:
                pass  # Ziel-Widget wurde inzwischen gelöscht
