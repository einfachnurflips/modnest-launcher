"""ModNest Launcher – Minecraft-Launcher mit Modrinth/CurseForge und sortierbaren Kategorien.

Aufruf:
    pythonw main.py                    Launcher starten
    python main.py --create-shortcuts  Verknüpfungen (Ordner + Desktop) ohne Konsolenfenster anlegen
    pythonw main.py --play "Ordner"    eine Instanz direkt starten (für Desktop-Verknüpfungen)
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
    # Läuft ModNest schon? Dann den Befehl dorthin schicken, statt ein zweites Fenster zu öffnen
    command = "show"
    if _arg("--play"):
        command = "play:" + _arg("--play")
        if _arg("--server"):
            command += "\nserver:" + _arg("--server")
        elif _arg("--world"):
            command += "\nworld:" + _arg("--world")
    if _send_to_running(command):
        return 0
    from modnest.config import APP_NAME, Settings, data_dir
    from modnest.i18n import set_language, tr
    from modnest.ui.icons import app_icon
    from modnest.ui.splash import Splash
    from modnest.ui.style import build_style

    first_run = not (data_dir() / "settings.json").exists()
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

    next_step = ""
    if first_run:
        splash.hide()
        from modnest.ui.wizard import SetupWizard
        wizard = SetupWizard(settings)
        wizard.exec()
        next_step = wizard.next_step
        app.setStyleSheet(build_style(data_dir(), settings.theme))
        if qt_translator.load(f"qtbase_{settings.language}",
                              QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(qt_translator)
        splash.show()

    splash.step(tr("Lade Module …"), 40, 250)
    from modnest.ui.main_window import MainWindow  # noqa: E402 – schwerer Import, erst nach dem Splash

    splash.step(tr("Lade Instanzen, Mods & Packs …"), 75, 300)
    window = MainWindow(settings)

    splash.step(tr("Fertig!"), 100, 300)
    splash.finish(window)
    if next_step == "packs":
        window.show_page("packs")
    elif next_step == "new":
        window.new_instance()
    elif next_step == "import":
        window.import_launchers()
    server = _listen(window)  # noqa: F841 – muss am Leben bleiben
    if command.startswith("play:"):
        window.handle_command(command)
    return app.exec()


def _server_name() -> str:
    import getpass
    return f"ModNest-{getpass.getuser()}"


def _send_to_running(command: str) -> bool:
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(500):
        return False
    sock.write(command.encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def _listen(window):
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    QLocalServer.removeServer(_server_name())
    server.listen(_server_name())

    def on_connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return

        def read():
            data = bytes(sock.readAll()).decode("utf-8", errors="replace").strip()
            if data:
                window.handle_command(data)
            sock.disconnectFromServer()

        sock.readyRead.connect(read)

    server.newConnection.connect(on_connection)
    return server


def _arg(name: str) -> str:
    if name in sys.argv:
        idx = sys.argv.index(name)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return ""


if __name__ == "__main__":
    if "--create-shortcuts" in sys.argv:
        create_shortcuts()
        sys.exit(0)
    if "--uninstall" in sys.argv:
        from modnest.config import Settings
        from modnest.i18n import set_language
        from modnest.updater import uninstall
        set_language(Settings.load().language)
        sys.exit(uninstall())
    sys.exit(main())
