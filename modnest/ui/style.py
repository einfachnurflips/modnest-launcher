"""Design: Farbpaletten für Dunkel/Hell und das Stylesheet als Vorlage ($token wird ersetzt)."""
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
}

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
    return PALETTES[_current][token]


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
QPushButton#play:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6ee7b7, stop:1 $accent); }
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


def build_style(data_dir, theme: str = "dark") -> str:
    """Erzeugt das Stylesheet für die gewählte Palette und merkt sie sich für color()."""
    global _current
    _current = resolve_theme(theme)
    style = STYLE.substitute(PALETTES[_current])
    path = data_dir / "check.svg"
    try:
        if not path.exists():
            path.write_text(CHECK_SVG, encoding="utf-8")
    except OSError:
        return style.replace("image: url(CHECK_SVG);", "")
    return style.replace("CHECK_SVG", path.as_posix())
