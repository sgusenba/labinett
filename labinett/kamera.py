"""Webcam im Hintergrund lesen und Auto-Aufnahme auslösen."""

from __future__ import annotations

import sys
import threading
import time
from collections import deque
from collections.abc import Callable

import cv2
import numpy as np

from .erkennung import schnell_ecken


def _diagonale(ecken: np.ndarray) -> float:
    return float(max(np.linalg.norm(ecken[0] - ecken[2]), np.linalg.norm(ecken[1] - ecken[3])))


def ecken_ruhig(a: np.ndarray | None, b: np.ndarray | None, toleranz_rel: float) -> bool:
    """Keine Ecke hat sich um mehr als ``toleranz_rel`` × Rautendiagonale bewegt."""
    if a is None or b is None:
        return False
    tol = max(2.0, toleranz_rel * _diagonale(a))
    return float(np.max(np.linalg.norm(a - b, axis=1))) <= tol


class Kamera:
    """Liest Frames, erkennt die Raute live und meldet stabile Karten.

    Eine Auto-Aufnahme wird ausgelöst, wenn die Raute ``stabile_frames`` Frames
    lang ruhig liegt. Übergeben werden die letzten ``aufnahme_bilder`` ruhigen
    Frames, damit die Auswertung über mehrere Bilder abstimmen kann. Danach muss
    die Karte erst wieder aus dem Bild, bevor die nächste Auto-Aufnahme möglich ist.

    ``sperren``: Nach einer Einlaufzeit werden Autofokus, Belichtung und
    Weißabgleich auf den aktuellen Werten festgehalten, damit das Bild nicht
    ständig nachgeregelt wird. Was die Kamera nicht unterstützt, wird übersprungen.
    """

    LEER_BIS_FREIGABE = 5  # so viele Frames ohne Karte, bis die Sperre fällt
    EINLAUF_S = 3.0  # Sekunden Automatik, bevor die Werte festgehalten werden

    def __init__(
        self,
        index: int,
        breite: int,
        hoehe: int,
        stabile_frames: int,
        bei_aufnahme: Callable[[list[np.ndarray]], None],
        aufnahme_bilder: int = 3,
        toleranz_rel: float = 0.01,
        sperren: bool = True,
        fokus: int = -1,
        mjpg: bool = True,
    ) -> None:
        self.index = index
        self.breite = breite
        self.hoehe = hoehe
        self.stabile_frames = stabile_frames
        self.bei_aufnahme = bei_aufnahme
        self.aufnahme_bilder = max(1, aufnahme_bilder)
        self.toleranz_rel = toleranz_rel
        self.sperren = sperren
        self.fokus = fokus
        self.mjpg = mjpg
        self.auto_aktiv = True
        self.fps: float | None = None  # gemessene Bilder pro Sekunde

        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._ruhig: deque[np.ndarray] = deque(maxlen=self.aufnahme_bilder)
        self._ecken: np.ndarray | None = None
        self._glatt: np.ndarray | None = None  # geglättete Ecken nur für die Anzeige
        self._stabil = 0
        self._gesperrt = False  # nach Aufnahme bis Karte entfernt
        self._leer = 0
        self._laeuft = False
        self._thread: threading.Thread | None = None
        self._dialog = False
        self._fokus_wunsch: int | None = None  # vom Bediener gewünschter Fokus, im Lesethread gesetzt
        self.fokus_aktuell: float | None = None
        self.autofokus = True
        self.fehler: str | None = None
        self.festgehalten: dict[str, bool] = {}

    # ------------------------------------------------------------ Steuerung

    def start(self) -> None:
        self._laeuft = True
        self._thread = threading.Thread(target=self._schleife, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._laeuft = False
        if self._thread:
            self._thread.join(timeout=2)

    def frame(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def frames(self) -> list[np.ndarray]:
        """Letzte ruhige Frames (für manuelle Aufnahme), sonst das aktuelle Bild."""
        with self._lock:
            if self._ecken is not None and len(self._ruhig) > 0:
                return [f.copy() for f in self._ruhig]
            return [] if self._frame is None else [self._frame.copy()]

    def treiber_dialog(self) -> None:
        """Einstellungsdialog des Kameratreibers öffnen (Windows/DirectShow)."""
        self._dialog = True

    def fokus_setzen(self, wert: int) -> None:
        """Fokus live ändern: ``wert`` ≥ 0 = fester Fokus, -1 = Autofokus neu scharfstellen lassen.

        Bei -1 läuft der Autofokus wieder, und – wenn ``sperren`` aktiv ist – wird der
        eingeregelte Wert nach der Einlaufzeit erneut festgehalten.
        """
        self._fokus_wunsch = int(wert)

    def status(self) -> dict:
        with self._lock:
            return {
                "kamera_ok": self._frame is not None and self.fehler is None,
                "fehler": self.fehler,
                "karte_erkannt": self._ecken is not None,
                "stabil": min(1.0, self._stabil / max(1, self.stabile_frames)),
                "wartet_auf_neue_karte": self._gesperrt,
                "auto_aktiv": self.auto_aktiv,
                "festgehalten": dict(self.festgehalten),
                "fokus": self.fokus_aktuell,
                "autofokus": self.autofokus,
                "fps": None if self.fps is None else round(self.fps, 1),
            }

    def vorschau_jpeg(self) -> bytes | None:
        with self._lock:
            if self._frame is None:
                return None
            bild = self._frame.copy()
            ecken = None if self._glatt is None else self._glatt.copy()
            stabil = self._stabil
            gesperrt = self._gesperrt
        if ecken is not None:
            farbe = (0, 200, 0) if gesperrt or stabil >= self.stabile_frames else (0, 200, 255)
            cv2.polylines(bild, [np.round(ecken).astype(np.int32)], True, farbe, 4, cv2.LINE_AA)
        h, w = bild.shape[:2]
        f = min(1.0, 960 / w)
        if f < 1:
            bild = cv2.resize(bild, None, fx=f, fy=f)
        ok, buf = cv2.imencode(".jpg", bild, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else None

    # ------------------------------------------------------------ intern

    def _oeffnen(self) -> cv2.VideoCapture:
        api = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.index, api)
        try:
            # MJPG vor der Auflösung setzen: unkomprimiert schaffen USB-2-Webcams
            # bei 1920 × 1080 oft nur 5 Bilder/s, mit MJPG 30.
            if self.mjpg:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.breite)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.hoehe)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # kein Rückstau alter Bilder
        except cv2.error:
            pass
        return cap

    def _festhalten(self, cap: cv2.VideoCapture) -> None:
        """Automatiken abschalten und die gerade eingeregelten Werte behalten."""
        erg: dict[str, bool] = {}

        def setze(prop: int, wert: float) -> bool:
            try:
                return bool(cap.set(prop, wert))
            except cv2.error:
                return False

        fokus = self.fokus if self.fokus >= 0 else cap.get(cv2.CAP_PROP_FOCUS)
        erg["fokus"] = setze(cv2.CAP_PROP_AUTOFOCUS, 0) | setze(cv2.CAP_PROP_FOCUS, fokus)
        self.autofokus = not erg["fokus"]
        belichtung = cap.get(cv2.CAP_PROP_EXPOSURE)
        # DirectShow schaltet beim Setzen eines Werts auf manuell, V4L2 braucht AUTO_EXPOSURE=1/0.25
        manuell = 0.25 if not sys.platform.startswith("win") else 0
        erg["belichtung"] = setze(cv2.CAP_PROP_AUTO_EXPOSURE, manuell) | setze(cv2.CAP_PROP_EXPOSURE, belichtung)
        wb = cap.get(cv2.CAP_PROP_WB_TEMPERATURE)
        erg["weissabgleich"] = setze(cv2.CAP_PROP_AUTO_WB, 0) | (wb > 0 and setze(cv2.CAP_PROP_WB_TEMPERATURE, wb))
        self.festgehalten = erg

    def _fokus_anwenden(self, cap: cv2.VideoCapture, wert: int) -> bool:
        """Gewünschten Fokus setzen; True = Autofokus läuft wieder (Einlauf neu starten)."""
        try:
            if wert < 0:
                self.fokus = -1
                self.autofokus = True
                cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
                return True
            self.fokus = wert
            self.autofokus = False
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            cap.set(cv2.CAP_PROP_FOCUS, wert)
        except cv2.error:
            pass
        return False

    def _fokus_lesen(self, cap: cv2.VideoCapture) -> None:
        try:
            self.fokus_aktuell = float(cap.get(cv2.CAP_PROP_FOCUS))
        except cv2.error:
            self.fokus_aktuell = None

    def _glaetten(self, ecken: np.ndarray | None) -> None:
        if ecken is None:
            self._glatt = None
        elif self._glatt is None or not ecken_ruhig(ecken, self._glatt, 0.05):
            self._glatt = ecken.astype(np.float64)
        else:
            self._glatt = self._glatt + 0.4 * (ecken - self._glatt)

    def _schleife(self) -> None:
        cap = self._oeffnen()
        letzte = None
        start = time.monotonic()
        festgehalten = not self.sperren
        n = 0
        letzt_t: float | None = None
        while self._laeuft:
            if not cap.isOpened():
                self.fehler = f"Kamera {self.index} lässt sich nicht öffnen"
                time.sleep(2)
                cap.release()
                cap = self._oeffnen()
                start = time.monotonic()
                festgehalten = not self.sperren
                continue
            if self._dialog:
                self._dialog = False
                try:
                    cap.set(cv2.CAP_PROP_SETTINGS, 1)
                except cv2.error:
                    pass
            if self._fokus_wunsch is not None:
                wunsch, self._fokus_wunsch = self._fokus_wunsch, None
                if self._fokus_anwenden(cap, wunsch):
                    start = time.monotonic()
                    festgehalten = not self.sperren
                self._fokus_lesen(cap)
            n += 1
            if n % 15 == 0:  # Autofokus wandert, Anzeige gelegentlich nachziehen
                self._fokus_lesen(cap)
            ok, frame = cap.read()
            if not ok:
                self.fehler = "Kein Bild von der Kamera"
                time.sleep(0.5)
                continue
            self.fehler = None
            jetzt = time.monotonic()
            if letzt_t is not None and jetzt > letzt_t:
                f = 1.0 / (jetzt - letzt_t)
                self.fps = f if self.fps is None else self.fps + 0.1 * (f - self.fps)
            letzt_t = jetzt
            if not festgehalten and time.monotonic() - start >= self.EINLAUF_S:
                try:
                    self._festhalten(cap)
                except Exception:  # Kamera ohne diese Eigenschaften: Automatik bleibt
                    self.festgehalten = {}
                festgehalten = True
                self._fokus_lesen(cap)
            ecken = schnell_ecken(frame)
            fertig: list[np.ndarray] | None = None
            with self._lock:
                self._frame = frame
                self._ecken = ecken
                self._glaetten(ecken)
                if ecken is None:
                    self._leer += 1
                    self._stabil = 0
                    self._ruhig.clear()
                    if self._leer >= self.LEER_BIS_FREIGABE:
                        self._gesperrt = False
                else:
                    self._leer = 0
                    if ecken_ruhig(ecken, letzte, self.toleranz_rel):
                        self._stabil += 1
                    else:
                        self._stabil = 0
                        self._ruhig.clear()
                    self._ruhig.append(frame)
                    if self.auto_aktiv and not self._gesperrt and self._stabil >= self.stabile_frames:
                        self._gesperrt = True
                        fertig = [f.copy() for f in self._ruhig]
            letzte = ecken
            if fertig:
                try:
                    self.bei_aufnahme(fertig)
                except Exception as e:  # Auswertung darf die Kamera nicht stoppen
                    self.fehler = f"Auswertung fehlgeschlagen: {e}"
        cap.release()
