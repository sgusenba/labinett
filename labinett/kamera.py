"""Webcam im Hintergrund lesen und Auto-Aufnahme auslösen."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

import cv2
import numpy as np

from .erkennung import ecken_stabil, schnell_ecken


class Kamera:
    """Liest Frames, erkennt die Raute live und meldet stabile Karten.

    Eine Auto-Aufnahme wird ausgelöst, wenn die Raute ``stabile_frames`` Frames
    lang ruhig liegt. Danach muss die Karte erst wieder aus dem Bild, bevor die
    nächste Auto-Aufnahme möglich ist.
    """

    def __init__(
        self,
        index: int,
        breite: int,
        hoehe: int,
        stabile_frames: int,
        bei_aufnahme: Callable[[np.ndarray], None],
    ) -> None:
        self.index = index
        self.breite = breite
        self.hoehe = hoehe
        self.stabile_frames = stabile_frames
        self.bei_aufnahme = bei_aufnahme
        self.auto_aktiv = True

        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._ecken: np.ndarray | None = None
        self._stabil = 0
        self._gesperrt = False  # nach Aufnahme bis Karte entfernt
        self._leer = 0
        self._laeuft = False
        self._thread: threading.Thread | None = None
        self.fehler: str | None = None

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

    def status(self) -> dict:
        with self._lock:
            return {
                "kamera_ok": self._frame is not None and self.fehler is None,
                "fehler": self.fehler,
                "karte_erkannt": self._ecken is not None,
                "stabil": min(1.0, self._stabil / max(1, self.stabile_frames)),
                "wartet_auf_neue_karte": self._gesperrt,
                "auto_aktiv": self.auto_aktiv,
            }

    def vorschau_jpeg(self) -> bytes | None:
        with self._lock:
            if self._frame is None:
                return None
            bild = self._frame.copy()
            ecken = None if self._ecken is None else self._ecken.copy()
            stabil = self._stabil
            gesperrt = self._gesperrt
        if ecken is not None:
            farbe = (0, 200, 0) if gesperrt or stabil >= self.stabile_frames else (0, 200, 255)
            cv2.polylines(bild, [ecken.astype(np.int32)], True, farbe, 4)
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
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.breite)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.hoehe)
        return cap

    def _schleife(self) -> None:
        cap = self._oeffnen()
        letzte = None
        while self._laeuft:
            if not cap.isOpened():
                self.fehler = f"Kamera {self.index} lässt sich nicht öffnen"
                time.sleep(2)
                cap.release()
                cap = self._oeffnen()
                continue
            ok, frame = cap.read()
            if not ok:
                self.fehler = "Kein Bild von der Kamera"
                time.sleep(0.5)
                continue
            self.fehler = None
            ecken = schnell_ecken(frame)
            ausloesen = False
            with self._lock:
                self._frame = frame
                self._ecken = ecken
                if ecken is None:
                    self._leer += 1
                    self._stabil = 0
                    if self._leer >= 5:
                        self._gesperrt = False
                else:
                    self._leer = 0
                    self._stabil = self._stabil + 1 if ecken_stabil(ecken, letzte, 8.0) else 0
                    if (
                        self.auto_aktiv
                        and not self._gesperrt
                        and self._stabil >= self.stabile_frames
                    ):
                        self._gesperrt = True
                        ausloesen = True
            letzte = ecken
            if ausloesen:
                try:
                    self.bei_aufnahme(frame.copy())
                except Exception as e:  # Auswertung darf die Kamera nicht stoppen
                    self.fehler = f"Auswertung fehlgeschlagen: {e}"
        cap.release()
