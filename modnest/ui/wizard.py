"""Einrichtungs-Assistent beim allerersten Start: Sprache, Design, Konto, Arbeitsspeicher."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

from .. import accounts
from ..config import data_dir
from ..i18n import set_language, tr
from .dialogs import RamSlider
from .icons import logo_pixmap
from .style import build_style


class SetupWizard(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.store = accounts.AccountStore()
        self.next_step = ""          # "packs" | "new" | "import" | ""
        self.setWindowTitle("ModNest")
        self.setFixedSize(640, 480)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(28, 24, 28, 20)
        self._build()

    # --- Aufbau ------------------------------------------------------------
    def _build(self) -> None:
        while self.outer.count():
            item = self.outer.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear(item.layout())
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(logo_pixmap(40))
        head.addWidget(logo)
        self.title = QLabel()
        self.title.setObjectName("pagetitle")
        head.addWidget(self.title, 1)
        self.step_label = QLabel()
        self.step_label.setObjectName("hint")
        head.addWidget(self.step_label)
        self.outer.addLayout(head)
        self.pages = QStackedWidget()
        self.outer.addWidget(self.pages, 1)
        nav = QHBoxLayout()
        self.back = QPushButton(tr("Zurück"))
        self.back.clicked.connect(lambda: self._go(self.pages.currentIndex() - 1))
        nav.addWidget(self.back)
        nav.addStretch(1)
        self.skip = QPushButton(tr("Überspringen"))
        self.skip.clicked.connect(self._finish)
        nav.addWidget(self.skip)
        self.next = QPushButton(tr("Weiter"))
        self.next.setObjectName("primary")
        self.next.clicked.connect(lambda: self._go(self.pages.currentIndex() + 1))
        nav.addWidget(self.next)
        self.outer.addLayout(nav)
        self.titles = []
        self._page_language()
        self._page_design()
        self._page_account()
        self._page_ram()
        self._page_done()

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def _page(self, title: str, text: str) -> QVBoxLayout:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(12)
        intro = QLabel(text)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.pages.addWidget(page)
        self.titles.append(title)
        return lay

    def _choice_row(self, lay, options, current, on_pick) -> None:
        group = QButtonGroup(self)
        row = QHBoxLayout()
        for key, label in options:
            btn = QPushButton(label)
            btn.setObjectName("pill")
            btn.setCheckable(True)
            btn.setChecked(key == current)
            btn.setMinimumHeight(54)
            btn.clicked.connect(lambda _=False, k=key: on_pick(k))
            group.addButton(btn)
            row.addWidget(btn)
        lay.addLayout(row)

    def _page_language(self) -> None:
        lay = self._page(tr("Willkommen bei ModNest!"),
                         tr("Schön, dass du da bist. In vier kurzen Schritten ist alles eingerichtet.\n\n"
                            "Welche Sprache möchtest du? / Which language do you prefer?"))
        self._choice_row(lay, [("de", "🇩🇪  Deutsch"), ("en", "🇬🇧  English")], self.settings.language,
                         self._set_language)
        lay.addStretch(1)

    def _page_design(self) -> None:
        lay = self._page(tr("Design"), tr("Hell oder dunkel? Du kannst das später jederzeit in den Einstellungen ändern."))
        self._choice_row(lay, [("dark", tr("🌙  Dunkel")), ("light", tr("☀  Hell")), ("neon", tr("💜  Neon")), ("system", tr("🖥  Wie Windows"))],
                         self.settings.theme, self._set_theme)
        lay.addStretch(1)

    def _page_account(self) -> None:
        lay = self._page(tr("Dein Minecraft-Konto"),
                         tr("Mit deinem Microsoft-Konto spielst du online, auf Servern und mit deinem Skin. "
                            "Ohne Konto geht Einzelspieler und LAN mit einem frei wählbaren Namen."))
        ms = QPushButton(tr("🔐  Mit Microsoft anmelden"))
        ms.setObjectName("primary")
        ms.setMinimumHeight(44)
        ms.clicked.connect(self._microsoft)
        ms.setEnabled(bool(self.settings.ms_client_id.strip()))
        lay.addWidget(ms)
        if not self.settings.ms_client_id.strip():
            hint = QLabel(tr("Für den Microsoft-Login fehlt noch die Client-ID (siehe README). "
                             "Du kannst sie später in den Einstellungen eintragen."))
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            lay.addWidget(hint)
        or_label = QLabel(tr("– oder offline spielen als –"))
        or_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        or_label.setObjectName("hint")
        lay.addWidget(or_label)
        self.offline_name = QLineEdit()
        self.offline_name.setPlaceholderText(tr("Spielername (3–16 Zeichen)"))
        self.offline_name.setMaxLength(16)
        lay.addWidget(self.offline_name)
        self.account_status = QLabel()
        self.account_status.setObjectName("hint")
        self.account_status.setWordWrap(True)
        lay.addWidget(self.account_status)
        ms_acc = next((a for a in self.store.accounts if a.kind == "microsoft"), None)
        if ms_acc:
            self.account_status.setText(tr("✔ Angemeldet als {name}.").format(name=ms_acc.name))
        lay.addStretch(1)

    def _page_ram(self) -> None:
        lay = self._page(tr("Arbeitsspeicher"),
                         tr("Wie viel Arbeitsspeicher darf Minecraft nutzen? Die Empfehlung passt für die meisten "
                            "Modpacks – große Packs bekommen automatisch mehr."))
        self.ram = RamSlider(self.settings.ram_mb)
        lay.addWidget(self.ram)
        lay.addStretch(1)

    def _page_done(self) -> None:
        lay = self._page(tr("Fertig! 🎉"), tr("Womit möchtest du loslegen?"))
        for key, text in (("packs", tr("📦  Ein fertiges Modpack aussuchen")),
                          ("new", tr("＋  Eine eigene Instanz erstellen")),
                          ("import", tr("🔄  Instanzen aus einem anderen Launcher übernehmen"))):
            btn = QPushButton(text)
            btn.setMinimumHeight(48)
            btn.clicked.connect(lambda _=False, k=key: self._finish(k))
            lay.addWidget(btn)
        lay.addStretch(1)

    # --- Logik -------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._go(self.pages.currentIndex())

    def _go(self, index: int) -> None:
        if self.pages.currentIndex() == 2 and index == 3 and not self._save_offline():
            return
        index = max(0, min(index, self.pages.count() - 1))
        self.pages.setCurrentIndex(index)
        self.title.setText(self.titles[index])
        self.step_label.setText(tr("Schritt {n} von {total}").format(n=index + 1, total=self.pages.count()))
        self.back.setVisible(index > 0)
        last = index == self.pages.count() - 1
        self.next.setVisible(not last)
        self.skip.setText(tr("Schließen") if last else tr("Überspringen"))

    def _set_language(self, lang: str) -> None:
        if lang == self.settings.language:
            self._go(1)
            return
        self.settings.language = lang
        set_language(lang)
        self._build()              # Texte in der neuen Sprache neu aufbauen
        self._go(1)

    def _set_theme(self, theme: str) -> None:
        self.settings.theme = theme
        QApplication.instance().setStyleSheet(build_style(data_dir(), theme, self.settings.accent))

    def _microsoft(self) -> None:
        from .login_dialog import MicrosoftLoginDialog
        dlg = MicrosoftLoginDialog(self.settings, self)
        if dlg.exec() and dlg.account:
            self.store.add(dlg.account)
            self.account_status.setText(tr("✔ Angemeldet als {name}.").format(name=dlg.account.name))
            self._go(3)

    def _save_offline(self) -> bool:
        name = self.offline_name.text().strip()
        if not name:
            return True
        if not (3 <= len(name) <= 16) or not all(c.isascii() and (c.isalnum() or c == "_") for c in name):
            self.account_status.setText(tr("Ungültiger Name. Erlaubt sind 3–16 Zeichen: A–Z, 0–9 und _."))
            return False
        self.store.add(accounts.offline_account(name))
        self.settings.username = name
        return True

    def _finish(self, step: str = "") -> None:
        if self.pages.currentIndex() == 2:
            self._save_offline()
        self.settings.ram_mb = self.ram.value()
        self.settings.extra["setup_done"] = True
        self.settings.save()
        self.next_step = step if isinstance(step, str) else ""
        self.accept()
