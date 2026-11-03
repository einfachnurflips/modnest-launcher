ACCENT = "#10b981"

STYLE = """
* { font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; color: #e5e7eb; }
QMainWindow, QWidget#root, QWidget#content { background: #0f1218; }
QWidget { background: transparent; }
QDialog { background: #141821; }
QToolTip { background: #1b2130; color: #e5e7eb; border: 1px solid #2a3344; padding: 6px 8px; border-radius: 6px; }

/* Seitenleiste */
#sidebar { background: #0b0d12; border-right: 1px solid #1a1f2a; }
#brand { font-size: 15pt; font-weight: 700; color: #f8fafc; font-family: "Segoe UI Variable Display", "Segoe UI"; }
#brandsub { color: #5b6474; font-size: 8pt; }
#section { color: #5b6474; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }
QListWidget#instances { background: transparent; border: none; outline: none; }
QListWidget#instances::item { padding: 6px 8px; border-radius: 10px; color: #cbd5e1; margin: 1px 0; }
QListWidget#instances::item:hover { background: #151a24; }
QListWidget#instances::item:selected { background: #172a24; color: #f8fafc; border: 1px solid #1f4a3b; }

/* Kopfbereich */
#title { font-size: 22pt; font-weight: 700; color: #f8fafc; font-family: "Segoe UI Variable Display", "Segoe UI"; }
#chip, #chipaccent { background: #1a1f2b; border: 1px solid #262e3d; border-radius: 10px; padding: 3px 10px;
                     color: #aab3c2; font-size: 9pt; }
#chipaccent { background: #11281f; border-color: #1d4d3a; color: #6ee7b7; }
#hint { color: #7d8796; }
#empty { color: #5b6474; font-size: 10pt; padding: 10px; }
#dialogtitle { font-size: 15pt; font-weight: 700; color: #f8fafc; }
#devicecode { font-size: 26pt; font-weight: bold; letter-spacing: 4px; color: #34d399; padding: 14px; }

/* Buttons */
QPushButton { background: #1a1f2b; border: 1px solid #262e3d; border-radius: 8px; padding: 7px 14px; color: #e5e7eb; }
QPushButton:hover { background: #222939; border-color: #334055; }
QPushButton:pressed { background: #151a24; }
QPushButton:disabled { color: #4b5563; background: #141821; border-color: #1c222e; }
QPushButton#iconbtn { padding: 6px; min-width: 22px; font-size: 11pt; }
QPushButton#ghost { background: transparent; border: 1px solid transparent; text-align: left; padding: 9px 12px; color: #aab3c2; }
QPushButton#ghost:hover { background: #151a24; color: #f1f5f9; }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10b981, stop:1 #059669);
                      border: none; font-weight: 600; color: white; padding: 8px 18px; }
QPushButton#primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #34d399, stop:1 #10b981); }
QPushButton#primary:disabled { background: #173329; color: #4f7d69; }
QPushButton#pill { background: #151a24; border: 1px solid #222a38; border-radius: 16px; padding: 6px 16px; color: #aab3c2; }
QPushButton#pill:hover { color: #f1f5f9; border-color: #334055; }
QPushButton#pill:checked { background: #11281f; border-color: #10b981; color: #6ee7b7; font-weight: 600; }
QPushButton#play {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #34d399, stop:1 #059669);
    border: none; border-radius: 12px; padding: 14px 44px; font-size: 13pt; font-weight: 800; color: white;
    letter-spacing: 1px;
}
QPushButton#play:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6ee7b7, stop:1 #10b981); }
QPushButton#play:disabled { background: #173329; color: #6ea08a; }
QPushButton#account { background: #151a24; border: 1px solid #222a38; border-radius: 12px; padding: 12px 16px; }
QPushButton#account:hover { border-color: #334055; }
QPushButton#account::menu-indicator { subcontrol-position: right center; right: 8px; }

/* Eingabefelder */
QLineEdit, QComboBox, QSpinBox {
    background: #151a24; border: 1px solid #242c3a; border-radius: 8px; padding: 7px 10px;
    selection-background-color: #10b981;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #10b981; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #151a24; border: 1px solid #242c3a; selection-background-color: #11281f;
                              selection-color: #6ee7b7; outline: none; padding: 4px; }
QCheckBox { spacing: 8px; color: #aab3c2; }
QCheckBox::indicator, QTreeWidget::indicator { width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #334055; background: #151a24; }
QCheckBox::indicator:checked, QTreeWidget::indicator:checked {
    background: #10b981; border-color: #10b981;
    image: url(CHECK_SVG);
}

/* Listen */
QTreeWidget { background: #121620; border: 1px solid #1c2230; border-radius: 12px; outline: none; padding: 4px; }
QTreeWidget::item { padding: 5px 4px; border: none; }
QTreeWidget::item:hover { background: #171d29; }
QTreeWidget::item:selected { background: #13291f; color: #f1f5f9; }
QTreeWidget::branch { background: transparent; }
QHeaderView { background: transparent; }
QHeaderView::section { background: transparent; border: none; border-bottom: 1px solid #1c2230; padding: 8px 6px;
                       color: #5b6474; font-size: 8pt; font-weight: 700; }

/* Tabs */
QTabWidget::pane { border: none; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background: transparent; padding: 9px 18px; margin-right: 6px; color: #7d8796; font-weight: 600;
               border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #f8fafc; border-bottom: 2px solid #10b981; }
QTabBar::tab:hover:!selected { color: #cbd5e1; }

/* Spielen-Leiste */
#playbar { background: #0b0d12; border-top: 1px solid #1a1f2a; }
#statustext { color: #aab3c2; }
QProgressBar { background: #1a1f2b; border: none; border-radius: 3px; }
QProgressBar::chunk { border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34d399, stop:1 #10b981); }

/* Menüs & Scrollbars */
QMenu { background: #151a24; border: 1px solid #242c3a; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: #13291f; color: #6ee7b7; }
QMenu::item:disabled { color: #4b5563; }
QMenu::separator { height: 1px; background: #242c3a; margin: 5px 8px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: #252d3b; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #334055; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { height: 0; background: none; }
QScrollBar:horizontal { height: 0; }
"""

CHECK_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'>"
    "<path d='M3.5 8.5l3 3 6-7' stroke='white' stroke-width='2' fill='none' "
    "stroke-linecap='round' stroke-linejoin='round'/></svg>"
)


def build_style(data_dir) -> str:
    """Schreibt das Häkchen-Bild in den Datenordner und setzt den Pfad ins Stylesheet ein."""
    path = data_dir / "check.svg"
    try:
        if not path.exists():
            path.write_text(CHECK_SVG, encoding="utf-8")
    except OSError:
        return STYLE.replace("image: url(CHECK_SVG);", "")
    return STYLE.replace("CHECK_SVG", path.as_posix())
