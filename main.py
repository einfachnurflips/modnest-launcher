"""ModNest Launcher – Minecraft-Launcher mit Modrinth/CurseForge und sortierbaren Kategorien.

Aufruf:
    pythonw main.py                    Launcher starten
    python main.py --create-shortcuts  Verknüpfungen (Ordner + Desktop) ohne Konsolenfenster anlegen
"""
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def create_shortcuts() -> None:
    """Legt "ModNest.lnk" im Launcher-Ordner und auf dem Desktop an (startet ohne Konsolenfenster)."""
    from PySide6.QtWidgets import QApplication

    from modnest.ui.icons import save_ico

    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 – für QPixmap nötig
    ico = APP_DIR / "ModNest.ico"
    save_ico(ico)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$desk = [Environment]::GetFolderPath('Desktop'); "
        "foreach ($p in @(($env:MN_DIR + '\\ModNest.lnk'), ($desk + '\\ModNest.lnk'))) { "
        "$s = $ws.CreateShortcut($p); $s.TargetPath = $env:MN_PYW; "
        "$s.Arguments = [char]34 + $env:MN_DIR + '\\main.py' + [char]34; "
        "$s.WorkingDirectory = $env:MN_DIR; $s.IconLocation = $env:MN_ICO; "
        "$s.Description = 'ModNest Minecraft Launcher'; $s.Save() }"
    )
    env = dict(__import__("os").environ, MN_DIR=str(APP_DIR), MN_PYW=str(pythonw), MN_ICO=str(ico))
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                   env=env, check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from modnest.config import APP_NAME, Settings, data_dir
    from modnest.i18n import set_language, tr
    from modnest.ui.icons import app_icon
    from modnest.ui.splash import Splash
    from modnest.ui.style import build_style

    settings = Settings.load()
    set_language(settings.language)
    # Qt-Standardtexte (z.B. „Speichern“/„Abbrechen“) in der gewählten Sprache
    from PySide6.QtCore import QLibraryInfo, QTranslator
    qt_translator = QTranslator(app)
    if qt_translator.load(f"qtbase_{settings.language}",
                          QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(qt_translator)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    splash = Splash()
    splash.show()
    app.processEvents()

    splash.step(tr("Lade Einstellungen …"), 15, 250)
    app.setStyleSheet(build_style(data_dir(), settings.theme))

    splash.step(tr("Lade Module …"), 40, 250)
    from modnest.ui.main_window import MainWindow  # noqa: E402 – schwerer Import, erst nach dem Splash

    splash.step(tr("Lade Instanzen, Mods & Packs …"), 75, 300)
    window = MainWindow(settings)

    splash.step(tr("Fertig!"), 100, 300)
    splash.finish(window)
    return app.exec()


if __name__ == "__main__":
    if "--create-shortcuts" in sys.argv:
        create_shortcuts()
        sys.exit(0)
    sys.exit(main())
