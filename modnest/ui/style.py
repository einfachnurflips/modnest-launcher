"""Design: Farbpaletten für Dunkel/Hell und das Stylesheet als Vorlage ($token wird ersetzt)."""
import re
import sys
from string import Template

PALETTES = {
    "dark": {
        "bg": "#0f1218", "sidebar": "#0b0d12", "surface": "#121620", "field": "#151a24", "button": "#1a1f2b",
        "card": "#141922", "border": "#1c2230", "border2": "#262e3d", "hover": "#171d29", "hover2": "#222939",
        "text": "#e5e7eb", "strong": "#f8fafc", "muted": "#8b93a1", "faint": "#5b6474", "disabled": "#4b5563",
        "accent": "#10b981", "accent_light": "#34d399", "accent_dark": "#059669", "accent_bg": "#11281f",
        "accent_border": "#1d4d3a", "accent_text": "#6ee7b7", "select": "#13291f", "dialog": "#141821",
        "danger": "#f87171", "warn": "#fbbf24", "shadow": "0, 0, 0",
    },
    "light": {
        "bg": "#f4f6f9", "sidebar": "#ffffff", "surface": "#ffffff", "field": "#ffffff", "button": "#ffffff",
        "card": "#ffffff", "border": "#e4e8ee", "border2": "#d6dce5", "hover": "#f1f4f8", "hover2": "#eef2f6",
        "text": "#1f2937", "strong": "#0b1220", "muted": "#5f6b7c", "faint": "#94a0b2", "disabled": "#a7b0bd",
        "accent": "#059669", "accent_light": "#10b981", "accent_dark": "#047857", "accent_bg": "#e6f6ef",
        "accent_border": "#9fdcc0", "accent_text": "#047857", "select": "#e3f5ec", "dialog": "#f8fafc",
        "danger": "#dc2626", "warn": "#d97706", "shadow": "15, 23, 42",
    },
    # Neon: schwarzer Grund, Pink und Cyan als Leuchtkanten zwischen den Elementen
    "neon": {
        "bg": "#000000", "sidebar": "#030306", "surface": "#05050a", "field": "#07070d", "button": "#08080f",
        "card": "#05050a", "border": "#00c8e6", "border2": "#ff2bd6", "hover": "#140a18", "hover2": "#1c0b22",
        "text": "#ecfeff", "strong": "#ffffff", "muted": "#8ad8e6", "faint": "#7a5c86", "disabled": "#4a3f55",
        "accent": "#ff2bd6", "accent_light": "#ff6be3", "accent_dark": "#c4129f", "accent_bg": "#1f0619",
        "accent_border": "#ff2bd6", "accent_text": "#ff8eea", "select": "#06222a", "dialog": "#020205",
        "danger": "#ff4d6d", "warn": "#ffe14d", "shadow": "0, 0, 0",
        "cyan": "#00e5ff",
    },
}

# Zusätzliche Regeln, die nur das Neon-Theme bekommt (am Ende angehängt, damit sie gewinnen)
NEON_EXTRA = Template("""
#sidebar { border-right: 1px solid $accent; }
#playbar { border-top: 1px solid $accent; }
#brand { color: $cyan; }
#section { color: $accent_light; }
#title, #pagetitle { color: $cyan; }
#h2 { color: $accent_light; }
QPushButton#nav:hover { border-color: $cyan; color: $cyan; background: transparent; }
QPushButton#nav:checked { background: $accent_bg; border: 1px solid $accent; color: $accent_text; }
QListWidget#instances::item:hover { border: 1px solid $cyan; }
QFrame#card, QFrame#newscard { border: 1px solid $cyan; }
QFrame#card:hover, QFrame#newscard:hover { border-color: $accent; }
QPushButton { border: 1px solid $cyan; }
QPushButton:hover { border-color: $accent; color: $strong; background: $hover2; }
QPushButton#ghost, QPushButton#avatar { border-color: transparent; }
QPushButton#ghost:hover { border-color: $cyan; }
QPushButton#primary, QPushButton#play { background: transparent; border: 2px solid $accent; color: $accent_text; }
QPushButton#primary:hover, QPushButton#play:hover { background: $accent; color: #000000; }
QPushButton#primary:disabled, QPushButton#play:disabled { border-color: $disabled; color: $disabled; background: transparent; }
QPushButton#join { border-color: $cyan; color: $cyan; background: transparent; }
QPushButton#join:hover { background: $cyan; color: #000000; }
QPushButton#pill:checked { border-color: $accent; }
QPushButton#account { border: 1px solid $accent; }
QLineEdit, QComboBox, QSpinBox, QTextBrowser { border: 1px solid $cyan; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: $accent; }
QTreeWidget, QListWidget { border: 1px solid $cyan; }
QTreeWidget::item:selected, QListWidget::item:selected { color: $cyan; }
QHeaderView::section { border-bottom: 1px solid $accent; color: $accent_light; }
QTabBar::tab:selected { color: $cyan; border-bottom: 2px solid $accent; }
QMenu { border: 1px solid $accent; }
QMenu::item:selected { color: $cyan; }
QToolTip { border: 1px solid $cyan; }
QDialog { border: 1px solid $accent; }
#chip { border-color: $cyan; color: $cyan; }
#chipaccent, #tag { border: 1px solid $accent; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $cyan); }
QSlider::sub-page:horizontal { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $cyan); }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: $accent_dark; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: $cyan; }
#ramvalue, #devicecode { color: $cyan; }
""")

_current = "dark"


def system_theme() -> str:
    """Hell/Dunkel-Einstellung von Windows."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
        except OSError:
            pass
    return "dark"


def resolve_theme(name: str) -> str:
    return system_theme() if name == "system" else (name if name in PALETTES else "dark")


def current() -> str:
    return _current


def color(token: str) -> str:
    """Farbe der aktuellen Palette – für Farben, die im Python-Code gesetzt werden."""
    return _active[token]


STYLE = Template("""
* { font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; color: $text; }
QMainWindow, QWidget#root, QWidget#content, QStackedWidget#pages > QWidget { background: $bg; }
QWidget { background: transparent; }
QDialog { background: $dialog; }
QToolTip { background: $field; color: $text; border: 1px solid $border2; padding: 6px 8px; border-radius: 6px; }
QLabel { background: transparent; }

/* Seitenleiste */
#sidebar { background: $sidebar; border-right: 1px solid $border; }
#brand { font-size: 15pt; font-weight: 700; color: $strong; font-family: "Segoe UI Variable Display", "Segoe UI"; }
#brandsub { color: $faint; font-size: 8pt; }
#section { color: $faint; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }
QPushButton#nav { background: transparent; border: 1px solid transparent; text-align: left; padding: 9px 12px;
                  border-radius: 10px; color: $muted; font-weight: 600; }
QPushButton#nav:hover { background: $hover; color: $strong; }
QPushButton#nav:checked { background: $accent_bg; color: $accent_text; border-color: $accent_border; }
QListWidget#instances { background: transparent; border: none; outline: none; }
QListWidget#instances::item { padding: 6px 8px; border-radius: 10px; color: $text; margin: 1px 0; }
QListWidget#instances::item:hover { background: $hover; }
QListWidget#instances::item:selected { background: $accent_bg; color: $strong; border: 1px solid $accent_border; }

/* Kopfbereich & Texte */
#title { font-size: 22pt; font-weight: 700; color: $strong; font-family: "Segoe UI Variable Display", "Segoe UI"; }
#pagetitle { font-size: 20pt; font-weight: 700; color: $strong; font-family: "Segoe UI Variable Display", "Segoe UI"; }
#h2 { font-size: 12pt; font-weight: 700; color: $strong; }
#chip, #chipaccent { background: $button; border: 1px solid $border2; border-radius: 10px; padding: 3px 10px;
                     color: $muted; font-size: 9pt; }
#chipaccent { background: $accent_bg; border-color: $accent_border; color: $accent_text; }
#hint { color: $muted; }
#empty { color: $faint; font-size: 10pt; padding: 10px; }
#dialogtitle { font-size: 15pt; font-weight: 700; color: $strong; }
#devicecode { font-size: 26pt; font-weight: bold; letter-spacing: 4px; color: $accent_light; padding: 14px; }
#ramvalue { font-size: 12pt; font-weight: 700; color: $accent_text; }
#online { color: $accent_light; font-weight: 600; }
#offline { color: $danger; font-weight: 600; }
#warn { color: $warn; }

/* Karten (Home) */
QFrame#card { background: $card; border: 1px solid $border; border-radius: 14px; }
QFrame#card:hover { border-color: $border2; }
QFrame#newscard { background: $card; border: 1px solid $border; border-radius: 14px; }
QFrame#newscard:hover { border-color: $accent_border; }
#cardtitle { font-weight: 700; color: $strong; font-size: 10.5pt; }
#cardtext { color: $muted; font-size: 9pt; }
#tag { background: $accent_bg; color: $accent_text; border-radius: 8px; padding: 2px 8px; font-size: 8pt; font-weight: 700; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* Buttons */
QPushButton { background: $button; border: 1px solid $border2; border-radius: 8px; padding: 7px 14px; color: $text; }
QPushButton:hover { background: $hover2; border-color: $faint; }
QPushButton:pressed { background: $hover; }
QPushButton:disabled { color: $disabled; background: $field; border-color: $border; }
QPushButton#iconbtn { padding: 6px; min-width: 22px; font-size: 11pt; }
QPushButton#ghost { background: transparent; border: 1px solid transparent; text-align: left; padding: 9px 12px; color: $muted; }
QPushButton#ghost:hover { background: $hover; color: $strong; }
QPushButton#avatar { background: transparent; border: none; padding: 0; border-radius: 14px; }
QPushButton#avatar:hover { background: $hover; }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent, stop:1 $accent_dark);
                      border: none; font-weight: 600; color: white; padding: 8px 18px; }
QPushButton#primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_light, stop:1 $accent); }
QPushButton#primary:disabled { background: $accent_bg; color: $faint; }
QPushButton#small { padding: 5px 12px; font-size: 9pt; }
QPushButton#join { background: $accent_bg; border: 1px solid $accent_border; color: $accent_text; font-weight: 700;
                   padding: 6px 14px; border-radius: 8px; }
QPushButton#join:hover { background: $accent; color: white; }
QPushButton#pill { background: $field; border: 1px solid $border2; border-radius: 16px; padding: 6px 16px; color: $muted; }
QPushButton#pill:hover { color: $strong; border-color: $faint; }
QPushButton#pill:checked { background: $accent_bg; border-color: $accent; color: $accent_text; font-weight: 600; }
QPushButton#play {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_light, stop:1 $accent_dark);
    border: none; border-radius: 12px; padding: 14px 44px; font-size: 13pt; font-weight: 800; color: white;
    letter-spacing: 1px;
}
QPushButton#play:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_text, stop:1 $accent); }
QPushButton#play:disabled { background: $accent_bg; color: $faint; }
QPushButton#account { background: $field; border: 1px solid $border2; border-radius: 12px; padding: 12px 16px; }
QPushButton#account:hover { border-color: $faint; }
QPushButton#account::menu-indicator { subcontrol-position: right center; right: 8px; }

/* Eingabefelder */
QLineEdit, QComboBox, QSpinBox, QTextBrowser {
    background: $field; border: 1px solid $border2; border-radius: 8px; padding: 7px 10px;
    selection-background-color: $accent; selection-color: white;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: $accent; }
QSpinBox::up-button, QSpinBox::down-button { width: 18px; border: none; background: transparent; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: $field; border: 1px solid $border2; selection-background-color: $select;
                              selection-color: $accent_text; outline: none; padding: 4px; }
QCheckBox, QRadioButton { spacing: 8px; color: $text; }
QCheckBox::indicator, QTreeWidget::indicator { width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid $border2; background: $field; }
QCheckBox::indicator:checked, QTreeWidget::indicator:checked { background: $accent; border-color: $accent; image: url(CHECK_SVG); }
QRadioButton::indicator { width: 16px; height: 16px; border-radius: 9px; border: 1px solid $border2; background: $field; }
QRadioButton::indicator:checked { border: 5px solid $accent; background: white; }
QSlider::groove:horizontal { height: 6px; background: $border2; border-radius: 3px; }
QSlider::sub-page:horizontal { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent_light, stop:1 $accent); border-radius: 3px; }
QSlider::handle:horizontal { background: white; border: 2px solid $accent; width: 16px; height: 16px; margin: -7px 0; border-radius: 10px; }

/* Listen */
QTreeWidget, QListWidget { background: $surface; border: 1px solid $border; border-radius: 12px; outline: none; padding: 4px; }
QTreeWidget::item, QListWidget::item { padding: 5px 4px; border: none; }
QTreeWidget::item:hover, QListWidget::item:hover { background: $hover; }
QTreeWidget::item:selected, QListWidget::item:selected { background: $select; color: $strong; }
QListWidget#gallery::item { border-radius: 10px; padding: 6px; margin: 4px; }
QTreeWidget::branch { background: transparent; }
QHeaderView { background: transparent; }
QHeaderView::section { background: transparent; border: none; border-bottom: 1px solid $border; padding: 8px 6px;
                       color: $faint; font-size: 8pt; font-weight: 700; }

/* Tabs */
QTabWidget::pane { border: none; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background: transparent; padding: 9px 18px; margin-right: 6px; color: $muted; font-weight: 600;
               border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $strong; border-bottom: 2px solid $accent; }
QTabBar::tab:hover:!selected { color: $text; }

/* Spielen-Leiste */
#playbar { background: $sidebar; border-top: 1px solid $border; }
#statustext { color: $muted; }
QProgressBar { background: $border2; border: none; border-radius: 3px; }
QProgressBar::chunk { border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent_light, stop:1 $accent); }

/* Menüs & Scrollbars */
QMenu { background: $field; border: 1px solid $border2; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; color: $text; }
QMenu::item:selected { background: $select; color: $accent_text; }
QMenu::item:disabled { color: $disabled; }
QMenu::separator { height: 1px; background: $border2; margin: 5px 8px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: $border2; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $faint; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { height: 0; width: 0; background: none; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px 4px; }
QScrollBar::handle:horizontal { background: $border2; border-radius: 3px; min-width: 30px; }
""")

CHECK_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'>"
    "<path d='M3.5 8.5l3 3 6-7' stroke='white' stroke-width='2' fill='none' "
    "stroke-linecap='round' stroke-linejoin='round'/></svg>"
)


ACCENTS = [   # Vorschläge für die eigene Akzentfarbe
    ("#3b82f6", "Blau"), ("#8b5cf6", "Violett"), ("#ec4899", "Pink"), ("#ef4444", "Rot"),
    ("#f97316", "Orange"), ("#eab308", "Gelb"), ("#06b6d4", "Cyan"),
]

_active = dict(PALETTES["dark"])


def _mix(a: str, b: str, amount: float) -> str:
    """Mischt Farbe a mit Anteil amount in Farbe b."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(ca, cb))


def with_accent(palette: dict, accent: str, light: bool) -> dict:
    """Ersetzt die Akzentfarben einer Palette durch eine eigene Farbe."""
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent or ""):
        return palette
    accent = accent.lower()
    pal = dict(palette)
    white, black = "#ffffff", "#000000"
    pal["accent"] = accent
    pal["accent_light"] = _mix(accent, white, 0.75)
    pal["accent_dark"] = _mix(accent, black, 0.75)
    pal["accent_bg"] = _mix(accent, pal["bg"], 0.14 if not light else 0.12)
    pal["accent_border"] = _mix(accent, pal["bg"], 0.40)
    pal["accent_text"] = _mix(accent, black, 0.65) if light else _mix(accent, white, 0.6)
    pal["select"] = _mix(accent, pal["surface"], 0.14)
    return pal


def build_style(data_dir, theme: str = "dark", accent: str = "") -> str:
    """Erzeugt das Stylesheet für die gewählte Palette und merkt sie sich für color()."""
    global _current, _active
    _current = resolve_theme(theme)
    _active = with_accent(PALETTES[_current], accent, _current == "light")
    style = STYLE.substitute(_active)
    if _current == "neon":
        style += NEON_EXTRA.substitute(_active)
    path = data_dir / "check.svg"
    try:
        if not path.exists():
            path.write_text(CHECK_SVG, encoding="utf-8")
    except OSError:
        return style.replace("image: url(CHECK_SVG);", "")
    return style.replace("CHECK_SVG", path.as_posix())
