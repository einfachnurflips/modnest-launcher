"""Einfache Übersetzung: Texte stehen auf Deutsch im Code, tr() liefert bei Englisch die Übersetzung.

Platzhalter werden mit str.format gefüllt:  tr("{n} Mods").format(n=3)
"""
from .i18n_en import EN

LANGUAGES = {"de": "Deutsch", "en": "English"}
_language = "de"


def set_language(lang: str) -> None:
    global _language
    _language = lang if lang in LANGUAGES else "de"


def language() -> str:
    return _language


def tr(text: str) -> str:
    if _language == "en":
        return EN.get(text, text)
    return text
