"""Ordnet neue Inhalte anhand der Modrinth-/CurseForge-Kategorien automatisch einer Launcher-Kategorie zu."""
from .instances import FALLBACK_CATEGORY

# Reihenfolge = Priorität: die erste passende Regel gewinnt
RULES = {
    "mods": [
        ("Bibliotheken", ["library", "api and library", "api"]),
        ("Performance", ["optimization", "performance"]),
        ("Grafik & Optik", ["cosmetic", "decoration", "shader", "resource", "visual", "render"]),
        ("Utility & QoL", ["utility", "qol", "management", "map and information", "social", "server utility"]),
        ("Gameplay & Inhalte", [
            "adventure", "magic", "technology", "worldgen", "world gen", "mobs", "food", "equipment",
            "game-mechanics", "game mechanics", "transportation", "storage", "armor", "weapons", "tools",
            "biomes", "dimensions", "structures", "redstone", "farming", "economy",
        ]),
    ],
    "resourcepacks": [
        ("PvP", ["pvp", "combat"]),
        ("Realistisch", ["realistic", "photo realistic", "semi-realistic"]),
        ("Stilisiert", ["cartoon", "simplistic", "themed", "medieval", "steampunk", "modern", "traditional"]),
        ("Vanilla+", ["vanilla-like", "vanilla", "tweaks", "utility", "fonts", "gui", "audio", "equipment"]),
    ],
    "shaderpacks": [
        ("Fantasy & Stilisiert", ["fantasy", "cartoon", "cursed", "stylized"]),
        ("Realistisch", ["realistic", "semi-realistic", "photo realistic", "screenshot"]),
        ("Leicht & schnell", ["potato", "low", "vanilla-like", "vanilla"]),
    ],
}


def guess_category(source_categories: list[str], available: list[str], kind: str = "mods") -> str:
    cats = [c.lower() for c in source_categories if c]
    for target, keywords in RULES.get(kind, []):
        if target not in available:
            continue
        # kurze Schlüsselwörter nur exakt, längere auch als Teilwort (z.B. 'api and library')
        if any(c == k or (len(k) > 4 and k in c) for c in cats for k in keywords):
            return target
    return FALLBACK_CATEGORY
