"""Formatierung von Zeiten und Dauern für die Oberfläche."""
import time
from ..i18n import tr



def ago(ts: float) -> str:
    if not ts:
        return tr("noch nie")
    diff = time.time() - ts
    if diff < 90:
        return tr("gerade eben")
    if diff < 3600:
        return tr("vor {n} Min.").format(n=int(diff // 60))
    if diff < 86400:
        return tr("vor {n} Std.").format(n=int(diff // 3600))
    days = int(diff // 86400)
    if days == 1:
        return tr("gestern")
    if days < 30:
        return tr("vor {n} Tagen").format(n=days)
    return time.strftime("%d.%m.%Y", time.localtime(ts))


def duration(seconds: int) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return tr("{m} Min.").format(m=minutes)
    hours, minutes = divmod(minutes, 60)
    return tr("{h} Std. {m} Min.").format(h=hours, m=minutes) if minutes else tr("{h} Std.").format(h=hours)
