"""Konten: Microsoft-Login (Device-Code-Flow) und Offline-Konten.

Ablauf Microsoft: Gerätecode → Microsoft-Token → Xbox Live → XSTS → Minecraft-Token → Profil.
Gespeichert wird nur der Refresh-Token, unter Windows mit DPAPI verschlüsselt (nur dein
Windows-Benutzer kann ihn entschlüsseln).
"""
import base64
import ctypes
import json
import sys
import time
import uuid as uuidlib
from ctypes import wintypes
from dataclasses import asdict, dataclass, fields

from .config import data_dir
from .game import offline_uuid
from .sources.base import SourceError, session
from .i18n import tr

MS_BASE = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
SCOPE = "XboxLive.signin offline_access"

XSTS_ERRORS = {
    2148916233: tr("Dieses Microsoft-Konto hat noch kein Xbox-Profil. Melde dich einmal auf xbox.com an und versuche es erneut."),
    2148916235: tr("Xbox Live ist in deinem Land nicht verfügbar."),
    2148916236: tr("Das Konto muss auf xbox.com noch als Erwachsenen-Konto verifiziert werden."),
    2148916237: tr("Das Konto muss auf xbox.com noch als Erwachsenen-Konto verifiziert werden."),
    2148916238: tr("Kinderkonto: Ein Erwachsener muss das Konto erst zu einer Microsoft-Familie hinzufügen."),
}


class LoginError(SourceError):
    pass


# --- Verschlüsselung (Windows DPAPI) -------------------------------------------
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("DPAPI-Fehler")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _protect(text: str) -> str:
    if sys.platform != "win32" or not text:
        return text
    return "dpapi:" + base64.b64encode(_dpapi(text.encode(), True)).decode()


def _unprotect(text: str) -> str:
    if not text.startswith("dpapi:"):
        return text
    return _dpapi(base64.b64decode(text[6:]), False).decode()


# --- Datenmodell -------------------------------------------------------------
@dataclass
class Account:
    kind: str                 # "microsoft" | "offline"
    name: str
    uuid: str
    refresh_token: str = ""   # verschlüsselt gespeichert
    mc_token: str = ""        # nur im Speicher
    mc_token_expires: float = 0

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.uuid}"

    @property
    def label(self) -> str:
        return f"{self.name} ({'Microsoft' if self.kind == 'microsoft' else 'Offline'})"


class AccountStore:
    def __init__(self):
        self.path = data_dir() / "accounts.json"
        self.accounts: list[Account] = []
        self.active_id = ""
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        names = {f.name for f in fields(Account)}
        for a in raw.get("accounts", []):
            acc = Account(**{k: v for k, v in a.items() if k in names})
            try:
                acc.refresh_token = _unprotect(acc.refresh_token)
            except OSError:
                acc.refresh_token = ""   # z.B. anderer Windows-Benutzer → neu anmelden
            self.accounts.append(acc)
        self.active_id = raw.get("active", "")

    def save(self) -> None:
        data = []
        for acc in self.accounts:
            d = asdict(acc)
            d["refresh_token"] = _protect(acc.refresh_token)
            d.pop("mc_token")
            d.pop("mc_token_expires")
            data.append(d)
        self.path.write_text(json.dumps({"active": self.active_id, "accounts": data}, indent=2), encoding="utf-8")

    @property
    def active(self) -> Account | None:
        return next((a for a in self.accounts if a.id == self.active_id), None) or (
            self.accounts[0] if self.accounts else None)

    def add(self, acc: Account) -> None:
        self.accounts = [a for a in self.accounts if a.id != acc.id] + [acc]
        self.active_id = acc.id
        self.save()

    def remove(self, acc: Account) -> None:
        self.accounts = [a for a in self.accounts if a.id != acc.id]
        if self.active_id == acc.id:
            self.active_id = self.accounts[0].id if self.accounts else ""
        self.save()

    def set_active(self, acc: Account) -> None:
        self.active_id = acc.id
        self.save()


def offline_account(name: str) -> Account:
    return Account(kind="offline", name=name, uuid=offline_uuid(name))


# --- Microsoft-Login ---------------------------------------------------------
def start_device_login(client_id: str) -> dict:
    """Fordert einen Gerätecode an. Antwort enthält user_code, verification_uri, device_code, interval."""
    if not client_id:
        raise LoginError(tr("Bitte zuerst in den Einstellungen eine Azure Client-ID eintragen (siehe README)."))
    resp = session.post(f"{MS_BASE}/devicecode", data={"client_id": client_id, "scope": SCOPE}, timeout=20)
    data = resp.json()
    if resp.status_code != 200:
        raise LoginError(_ms_error(data))
    return data


def poll_device_login(client_id: str, device: dict, cancelled) -> Account:
    """Wartet, bis der Nutzer den Code im Browser bestätigt hat, und meldet dann bei Minecraft an."""
    interval = int(device.get("interval", 5))
    deadline = time.time() + int(device.get("expires_in", 900))
    while time.time() < deadline:
        if cancelled():
            raise LoginError(tr("Anmeldung abgebrochen."))
        time.sleep(interval)
        resp = session.post(f"{MS_BASE}/token", data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": device["device_code"],
        }, timeout=20)
        data = resp.json()
        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error:
            raise LoginError(_ms_error(data))
        return _minecraft_login(data["access_token"], data["refresh_token"])
    raise LoginError(tr("Der Code ist abgelaufen. Bitte erneut anmelden."))


def refresh(acc: Account, client_id: str) -> Account:
    """Erneuert den Minecraft-Token, falls nötig. Gibt das aktualisierte Konto zurück."""
    if acc.kind != "microsoft" or (acc.mc_token and acc.mc_token_expires - time.time() > 600):
        return acc
    if not acc.refresh_token:
        raise LoginError(tr("Die Anmeldung von {name} ist abgelaufen. Bitte das Konto neu hinzufügen.").format(name=acc.name))
    resp = session.post(f"{MS_BASE}/token", data={
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": acc.refresh_token,
        "scope": SCOPE,
    }, timeout=20)
    data = resp.json()
    if resp.status_code != 200:
        raise LoginError(tr("Die Anmeldung von {name} ist abgelaufen. Bitte das Konto neu hinzufügen.").format(
            name=acc.name) + f"\n({_ms_error(data)})")
    fresh = _minecraft_login(data["access_token"], data.get("refresh_token", acc.refresh_token))
    acc.name, acc.refresh_token = fresh.name, fresh.refresh_token
    acc.mc_token, acc.mc_token_expires = fresh.mc_token, fresh.mc_token_expires
    return acc


def _minecraft_login(ms_token: str, refresh_token: str) -> Account:
    headers = {"Accept": "application/json"}
    # Xbox Live
    resp = session.post("https://user.auth.xboxlive.com/user/authenticate", json={
        "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com", "RpsTicket": f"d={ms_token}"},
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    }, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise LoginError(tr("Xbox-Live-Anmeldung fehlgeschlagen (HTTP {code}).").format(code=resp.status_code))
    xbl = resp.json()
    userhash = xbl["DisplayClaims"]["xui"][0]["uhs"]
    # XSTS
    resp = session.post("https://xsts.auth.xboxlive.com/xsts/authorize", json={
        "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl["Token"]]},
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    }, headers=headers, timeout=20)
    if resp.status_code != 200:
        xerr = (resp.json() if resp.content else {}).get("XErr")
        raise LoginError(XSTS_ERRORS.get(xerr, tr("XSTS-Anmeldung fehlgeschlagen (HTTP {code}, {xerr}).").format(code=resp.status_code, xerr=xerr)))
    xsts = resp.json()
    # Minecraft
    resp = session.post("https://api.minecraftservices.com/authentication/login_with_xbox", json={
        "identityToken": f"XBL3.0 x={userhash};{xsts['Token']}",
    }, headers=headers, timeout=20)
    if resp.status_code == 403:
        raise LoginError(
            tr("Minecraft hat die Anmeldung abgelehnt (403).\n\n"
            "Neue Azure-Apps müssen von Microsoft für die Minecraft-API freigeschaltet werden. "
            "Beantrage das unter https://aka.ms/mce-reviewappid – die Prüfung kann einige Tage dauern.")
        )
    if resp.status_code != 200:
        raise LoginError(tr("Minecraft-Anmeldung fehlgeschlagen (HTTP {code}).").format(code=resp.status_code))
    mc = resp.json()
    # Profil (schlägt fehl, wenn das Konto Minecraft nicht besitzt)
    resp = session.get("https://api.minecraftservices.com/minecraft/profile",
                       headers={"Authorization": f"Bearer {mc['access_token']}"}, timeout=20)
    if resp.status_code == 404:
        raise LoginError(tr("Dieses Microsoft-Konto besitzt Minecraft: Java Edition nicht."))
    if resp.status_code != 200:
        raise LoginError(tr("Minecraft-Profil konnte nicht geladen werden (HTTP {code}).").format(code=resp.status_code))
    profile = resp.json()
    return Account(
        kind="microsoft",
        name=profile["name"],
        uuid=str(uuidlib.UUID(profile["id"])),
        refresh_token=refresh_token,
        mc_token=mc["access_token"],
        mc_token_expires=time.time() + int(mc.get("expires_in", 86400)),
    )


def _ms_error(data: dict) -> str:
    code = data.get("error", "")
    desc = (data.get("error_description") or "").split("\r\n")[0]
    if "AADSTS7000218" in desc or "AADSTS70002" in desc:
        return (tr("Die Azure-App erlaubt keine Device-Code-Anmeldung. Aktiviere im Azure-Portal unter "
                "Authentifizierung → „Öffentliche Clientflows zulassen“."))
    if "AADSTS700016" in desc or "AADSTS700038" in desc:
        return tr("Die Client-ID wurde nicht gefunden. Bitte in den Einstellungen prüfen.")
    if code == "expired_token":
        return tr("Der Code ist abgelaufen. Bitte erneut anmelden.")
    if code in ("access_denied", "authorization_declined"):
        return tr("Anmeldung wurde im Browser abgelehnt.")
    return f"{code}: {desc}" if desc else (code or tr("Unbekannter Fehler"))
