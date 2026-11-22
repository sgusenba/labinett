"""Auto-Update der labinett.exe über GitHub-Releases.

Ablauf (nur in der gebauten Windows-.exe aktiv):

1. Start: Liegt von einem früheren Lauf eine fertig geladene ``labinett.exe.neu``
   bereit, wird sie eingespielt – laufende .exe in ``labinett.exe.alt``
   umbenennen (geht unter Windows auch bei laufendem Programm), ``.neu`` an ihre
   Stelle schieben, neue .exe starten und beenden. Das dauert unter einer Sekunde
   und braucht kein Netz.
2. Danach startet das Programm ganz normal. Im Hintergrund fragt ein Thread
   GitHub nach dem neuesten Release. Ohne Netz oder bei jedem Fehler passiert
   einfach nichts – der Start wird nie blockiert.
3. Ist die Version neuer, wird die .exe nach ``labinett.exe.download`` geladen,
   gegen die SHA-256 aus dem Release geprüft und erst dann in ``.neu``
   umbenannt. Die Oberfläche zeigt „Update bereit – wird beim nächsten Start
   installiert“.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = "sgusenba/labinett"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "labinett.exe"
TIMEOUT_S = 10


def version_tupel(text: str) -> tuple[int, ...] | None:
    """'v0.1.12' → (0, 1, 12); None für Entwicklungs- oder unlesbare Versionen."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", text.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def ist_neuer(kandidat: str, aktuell: str) -> bool:
    neu, alt = version_tupel(kandidat), version_tupel(aktuell)
    return neu is not None and alt is not None and neu > alt


def exe_pfad() -> Path | None:
    """Pfad der laufenden .exe – nur bei PyInstaller-Builds unter Windows."""
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return Path(sys.executable).resolve()
    return None


def _pfade(exe: Path) -> tuple[Path, Path, Path]:
    return (
        exe.with_name(exe.name + ".neu"),
        exe.with_name(exe.name + ".alt"),
        exe.with_name(exe.name + ".download"),
    )


def bereit_installieren(exe: Path, neustart=None) -> bool:
    """Schritt 1: liegt ein geprüftes Update bereit, einspielen und neu starten.

    Gibt True zurück, wenn neu gestartet wurde (Aufrufer beendet sich dann).
    Jeder Fehler wird geschluckt: lieber die alte Version starten als gar keine.
    """
    neu, alt, download = _pfade(exe)
    for rest in (alt, download):
        try:
            rest.unlink(missing_ok=True)  # Reste vom letzten Update
        except OSError:
            pass
    if not neu.exists():
        return False
    try:
        exe.replace(alt)
    except OSError:
        return False
    try:
        neu.replace(exe)
    except OSError:
        try:
            alt.replace(exe)  # zurückrollen
        except OSError:
            pass
        return False
    (neustart or _neu_starten)(exe)
    return True


def _neu_starten(exe: Path) -> None:
    # Eigenes Konsolenfenster nicht nötig: der neue Prozess erbt die Konsole.
    subprocess.Popen([str(exe), *sys.argv[1:]], close_fds=True)


@dataclass
class UpdateStatus:
    zustand: str = "aus"  # aus | pruefe | aktuell | laedt | bereit | fehler
    version: str = ""
    meldung: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def setzen(self, zustand: str, version: str = "", meldung: str = "") -> None:
        with self.lock:
            self.zustand, self.version, self.meldung = zustand, version, meldung

    def als_dict(self) -> dict:
        with self.lock:
            return {"zustand": self.zustand, "version": self.version, "meldung": self.meldung}


def _hole(url: str, accept: str = "application/json") -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "labinett-updater"})


def neuestes_release(oeffnen=urllib.request.urlopen) -> dict:
    with oeffnen(_hole(API_LATEST, "application/vnd.github+json"), timeout=TIMEOUT_S) as r:
        return json.load(r)


def _asset(release: dict, name: str) -> dict | None:
    return next((a for a in release.get("assets", []) if a.get("name") == name), None)


def herunterladen(url: str, ziel: Path, oeffnen=urllib.request.urlopen) -> str:
    """Datei laden, SHA-256 zurückgeben."""
    h = hashlib.sha256()
    with oeffnen(_hole(url, "application/octet-stream"), timeout=TIMEOUT_S) as r, open(ziel, "wb") as f:
        while block := r.read(1 << 16):
            h.update(block)
            f.write(block)
    return h.hexdigest()


def pruefen_und_laden(exe: Path, aktuell: str, status: UpdateStatus, oeffnen=urllib.request.urlopen) -> None:
    """Schritt 2+3, läuft im Hintergrund-Thread."""
    neu, _, download = _pfade(exe)
    status.setzen("pruefe")
    try:
        release = neuestes_release(oeffnen)
        tag = release.get("tag_name", "")
        if not ist_neuer(tag, aktuell):
            status.setzen("aktuell", aktuell)
            return
        version = tag.lstrip("v")
        exe_asset = _asset(release, ASSET_NAME)
        sha_asset = _asset(release, ASSET_NAME + ".sha256")
        if exe_asset is None or sha_asset is None:
            status.setzen("fehler", version, "Release ohne labinett.exe / Prüfsumme")
            return
        if neu.exists():
            neu.unlink()  # älterer, noch nicht installierter Download
        with oeffnen(_hole(sha_asset["browser_download_url"], "application/octet-stream"), timeout=TIMEOUT_S) as r:
            soll = r.read().decode("ascii", "replace").split()[0].lower()
        status.setzen("laedt", version)
        ist = herunterladen(exe_asset["browser_download_url"], download, oeffnen)
        if ist != soll:
            download.unlink(missing_ok=True)
            status.setzen("fehler", version, "Prüfsumme stimmt nicht – Update verworfen")
            return
        download.replace(neu)
        status.setzen("bereit", version, f"Version {version} wird beim nächsten Start installiert")
    except Exception as e:  # noqa: BLE001 – kein Netz, Rate-Limit, Proxy …: still weiterlaufen
        try:
            download.unlink(missing_ok=True)
        except OSError:
            pass
        status.setzen("fehler" if not isinstance(e, OSError) else "offline", "", type(e).__name__)


def hintergrund_starten(aktuell: str, status: UpdateStatus, exe: Path | None = None) -> threading.Thread | None:
    exe = exe or exe_pfad()
    if exe is None or version_tupel(aktuell) is None:
        return None  # Entwicklung/PR-Build: kein Update
    t = threading.Thread(target=pruefen_und_laden, args=(exe, aktuell, status), daemon=True, name="update")
    t.start()
    return t


def beim_start(aktiv: bool) -> None:
    """Vor allem anderen in main() aufrufen."""
    exe = exe_pfad()
    if exe is None or not aktiv or os.environ.get("LABINETT_KEIN_UPDATE"):
        return
    if bereit_installieren(exe):
        sys.exit(0)
