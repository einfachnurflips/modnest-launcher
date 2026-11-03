"""Performance-Paket: bewährte Performance-Mods mit einem Klick, passend zu Version und Loader."""
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .i18n import tr
from .instances import Instance
from .sources import SourceError, modrinth


@dataclass
class PerfMod:
    slug: str
    name: str
    what: str
    loaders: tuple
    conflicts: tuple = ()     # Mod-Namen/Slugs, bei denen diese Mod nicht vorgeschlagen wird


PERF_MODS = [
    PerfMod("sodium", "Sodium", tr("Neue Grafik-Engine – oft doppelte bis dreifache FPS"),
            ("fabric", "quilt", "neoforge"), ("optifine", "embeddium", "rubidium")),
    PerfMod("embeddium", "Embeddium", tr("Sodium für Forge – deutlich mehr FPS"),
            ("forge",), ("optifine", "sodium", "rubidium")),
    PerfMod("lithium", "Lithium", tr("Schnellere Spiel-Logik (Mobs, Redstone, Welt)"),
            ("fabric", "quilt", "neoforge"), ("canary", "radium")),
    PerfMod("ferrite-core", "FerriteCore", tr("Spart viel Arbeitsspeicher"),
            ("fabric", "quilt", "forge", "neoforge")),
    PerfMod("modernfix", "ModernFix", tr("Schnellerer Spielstart, weniger RAM"),
            ("fabric", "quilt", "forge", "neoforge")),
    PerfMod("entityculling", "Entity Culling", tr("Versteckte Mobs und Kisten werden nicht gezeichnet"),
            ("fabric", "quilt", "forge", "neoforge")),
    PerfMod("immediatelyfast", "ImmediatelyFast", tr("Schnellere Darstellung von Text, Karten und HUD"),
            ("fabric", "quilt", "forge", "neoforge")),
    PerfMod("dynamic-fps", "Dynamic FPS", tr("Weniger FPS im Hintergrund – spart Strom und Akku"),
            ("fabric", "quilt", "forge", "neoforge")),
]


@dataclass
class PerfOption:
    mod: PerfMod
    project: object = None      # sources.Project
    release: object = None      # sources.Release
    status: str = "ok"          # ok | installed | conflict | unavailable
    note: str = ""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _installed_names(instance: Instance) -> set:
    """Normalisierte Namen, Projekt-IDs und – bei lokalen Dateien – der Dateiname ohne Version."""
    names = set()
    for m in instance.mods:
        names.add(_norm(m.name))
        if m.project_id:
            names.add(_norm(m.project_id))
        stem = re.split(r"[-_+ ]?(?:mc)?\d", m.file.lower(), maxsplit=1)[0]
        names.add(_norm(stem))
        names.add(_norm(re.sub(r"[-_](fabric|forge|neoforge|quilt)$", "", stem)))
    return names


def _has(names: set, key: str) -> bool:
    return _norm(key) in names


def options(instance: Instance) -> list[PerfOption]:
    """Ermittelt, welche Performance-Mods für diese Instanz verfügbar sind."""
    if instance.loader == "vanilla":
        raise SourceError(tr("Vanilla-Instanzen können keine Mods laden. Erstelle eine Instanz mit Fabric oder NeoForge."))
    names = _installed_names(instance)
    candidates = [m for m in PERF_MODS if instance.loader in m.loaders]

    def resolve(mod: PerfMod) -> PerfOption:
        opt = PerfOption(mod)
        if _has(names, mod.slug) or _has(names, mod.name):
            opt.status, opt.note = "installed", tr("schon installiert")
            return opt
        clash = next((c for c in mod.conflicts if _has(names, c)), None)
        if clash:
            opt.status, opt.note = "conflict", tr("nicht zusammen mit {mod}").format(mod=clash)
            return opt
        try:
            opt.project = modrinth.get_project(mod.slug, "mods")
            opt.release = modrinth.resolve(opt.project.project_id, instance.mc_version, instance.loader, "mods")
        except (SourceError, OSError):
            opt.status, opt.note = "unavailable", tr("nicht für {mc} verfügbar").format(mc=instance.mc_version)
        return opt

    with ThreadPoolExecutor(6) as pool:
        return list(pool.map(resolve, candidates))
