"""Absturz-Helfer: liest Log und Crash-Report und sucht die wahrscheinliche Ursache."""
import re
from dataclasses import dataclass, field
from pathlib import Path
from .i18n import tr


@dataclass
class CrashInfo:
    reason: str
    tips: list[str] = field(default_factory=list)
    suspects: list[str] = field(default_factory=list)
    details: str = ""
    report: Path | None = None


def _tail(path: Path, max_chars: int = 400_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]


def analyze(instance_path: Path, started_at: float) -> CrashInfo:
    log = _tail(instance_path / "launcher-log.txt")
    report = None
    reports = instance_path / "crash-reports"
    if reports.is_dir():
        fresh = [p for p in reports.glob("*.txt") if p.stat().st_mtime >= started_at - 5]
        if fresh:
            report = max(fresh, key=lambda p: p.stat().st_mtime)
    report_text = _tail(report) if report else ""
    text = report_text + "\n" + log
    info = CrashInfo(tr("Minecraft wurde unerwartet beendet."), report=report)

    # Fabric/Quilt: fehlende oder inkompatible Abhängigkeiten
    if "Incompatible mods found" in text or "Incompatible mod set" in text:
        info.reason = tr("Inkompatible oder fehlende Mods")
        lines = re.findall(r"^\s*- (?:Mod|Replace|Install|Remove) .+$", text, re.MULTILINE)
        info.details = "\n".join(dict.fromkeys(l.strip() for l in lines[:12]))
        info.tips.append(tr("Installiere die genannten Mods bzw. Versionen oder entferne den betroffenen Mod."))
    # Forge/NeoForge: fehlende Abhängigkeiten
    elif "Missing or unsupported mandatory dependencies" in text:
        info.reason = tr("Fehlende Abhängigkeiten (Forge/NeoForge)")
        lines = re.findall(r"Mod ID: '([^']+)', Requested by: '([^']+)'.*", text)
        info.details = "\n".join(tr("{req} braucht {mid}").format(req=req, mid=mid) for mid, req in dict.fromkeys(lines))
        info.tips.append(tr("Installiere die fehlenden Mods über „Entdecken“."))
    elif "OutOfMemoryError" in text:
        info.reason = tr("Zu wenig Arbeitsspeicher")
        info.tips.append(tr("Erhöhe den Arbeitsspeicher unter ⚙ Einstellungen → Spiel."))
    elif "UnsupportedClassVersionError" in text:
        info.reason = tr("Falsche Java-Version")
        info.tips.append(tr("Lass das Java-Feld in den Einstellungen leer, dann nutzt ModNest automatisch das passende Java."))
    elif re.search(r"Mixin apply for mod \S+ failed|MixinApplyError|InvalidMixinException", text):
        info.reason = tr("Ein Mod ist mit dieser Version nicht kompatibel (Mixin-Fehler)")
        info.tips.append(tr("Aktualisiere den verdächtigen Mod oder deaktiviere ihn testweise."))
    elif "Could not create the Java Virtual Machine" in text or "Invalid maximum heap size" in text:
        info.reason = tr("Java konnte nicht gestartet werden")
        info.tips.append(tr("Prüfe den Arbeitsspeicher in den Einstellungen (nicht mehr als dein PC hat)."))

    # Verdächtige Mods sammeln
    suspects = re.findall(r"Mixin apply for mod (\S+) failed", text)
    suspects += re.findall(r"from mod (\w[\w-]*)", text)
    block = re.search(r"Suspected Mods?:\s*(.+?)(?:\n\s*\n|\nStacktrace)", report_text, re.DOTALL)
    if block:
        suspects += [s.strip(" \t-") for s in block.group(1).splitlines() if s.strip() and "Unknown" not in s]
    ignore = {"minecraft", "java", "fabricloader", "fabric", "forge", "neoforge", "mixinextras", "unknown"}
    info.suspects = [s for s in dict.fromkeys(suspects) if s.lower() not in ignore][:6]

    if not info.details:
        desc = re.search(r"^Description: (.+)$", report_text, re.MULTILINE)
        cause = re.findall(r"^(?:Caused by: )?([\w.$]+(?:Exception|Error)[^\n]*)$", text, re.MULTILINE)
        parts = []
        if desc:
            parts.append(desc.group(1).strip())
        if cause:
            parts.append(cause[-1].strip()[:300])
        info.details = "\n".join(parts)
    if not info.tips:
        info.tips.append(tr("Öffne den Crash-Report oder deaktiviere zuletzt installierte Mods testweise."))
    return info
