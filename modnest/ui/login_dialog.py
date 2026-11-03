"""Microsoft-Anmeldung per Gerätecode: Code anzeigen, Browser öffnen, auf Bestätigung warten."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import accounts
from .workers import run_task
from ..i18n import tr


class MicrosoftLoginDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.account = None
        self.device = None
        self._cancelled = False
        self.setWindowTitle(tr("Mit Microsoft anmelden"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        self.info = QLabel(tr("Fordere Anmeldecode an …"))
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.code = QLabel("")
        self.code.setObjectName("devicecode")
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.code)

        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.status.setOpenExternalLinks(True)
        layout.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        self.open_btn = QPushButton(tr("Code kopieren && Browser öffnen"))
        self.open_btn.setObjectName("primary")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_browser)
        row.addWidget(self.open_btn)
        cancel = QPushButton(tr("Abbrechen"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        layout.addLayout(row)

        client_id = settings.ms_client_id.strip()
        run_task(lambda: accounts.start_device_login(client_id), self._got_code, self._failed)

    def _got_code(self, device: dict) -> None:
        if self._cancelled:
            return
        self.device = device
        uri = device.get("verification_uri", "https://www.microsoft.com/link")
        self.info.setText(tr("1. Öffne <b>{uri}</b><br>2. Gib diesen Code ein und melde dich mit dem "
                             "Microsoft-Konto an, mit dem du Minecraft gekauft hast:").format(uri=uri))
        self.code.setText(device["user_code"])
        self.status.setText(tr("Warte auf Bestätigung im Browser …"))
        self.open_btn.setEnabled(True)
        client_id = self.settings.ms_client_id.strip()
        run_task(lambda: accounts.poll_device_login(client_id, device, lambda: self._cancelled),
                 self._logged_in, self._failed)

    def open_browser(self) -> None:
        if self.device:
            QGuiApplication.clipboard().setText(self.device["user_code"])
            QDesktopServices.openUrl(QUrl(self.device.get("verification_uri", "https://www.microsoft.com/link")))
            self.status.setText(tr("Code kopiert – im Browser einfügen. Warte auf Bestätigung …"))

    def _logged_in(self, account) -> None:
        if self._cancelled:
            return
        self.account = account
        self.accept()

    def _failed(self, err: str) -> None:
        if self._cancelled:
            return
        self.code.setText("")
        self.open_btn.setEnabled(False)
        self.info.setText(tr("<b>Anmeldung fehlgeschlagen</b>"))
        self.status.setText(err.replace("\n", "<br>"))

    def done(self, result: int) -> None:
        self._cancelled = True   # stoppt das Polling im Hintergrund
        super().done(result)
