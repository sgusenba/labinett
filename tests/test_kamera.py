"""Auto-Aufnahme mit simulierter Kamera."""

import threading
import time
from pathlib import Path

import cv2

from labinett.erkennung import schnell_ecken
from labinett.kamera import Kamera

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"


class FakeCap:
    def __init__(self, frames):
        self.frames = frames
        self.i = 0

    def isOpened(self):
        return True

    def read(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        time.sleep(0.005)
        return True, f

    def release(self):
        pass


def test_schnell_ecken_findet_raute():
    bild = cv2.imread(str(TESTDATA / "nikolo_04.jpg"))
    assert schnell_ecken(bild) is not None


def test_auto_aufnahme_einmal_pro_karte(monkeypatch):
    karte = cv2.imread(str(TESTDATA / "nikolo_04.jpg"))
    leer = karte.copy()
    leer[:] = 30
    # Karte liegt 15 Frames, wird entfernt (10 leere), wieder hingelegt (15)
    frames = [karte] * 15 + [leer] * 10 + [karte] * 15 + [leer] * 200
    aufnahmen = []
    fertig = threading.Event()

    def bei_aufnahme(frame):
        aufnahmen.append(frame.shape)
        if len(aufnahmen) == 2:
            fertig.set()

    k = Kamera(0, 640, 480, stabile_frames=5, bei_aufnahme=bei_aufnahme)
    monkeypatch.setattr(k, "_oeffnen", lambda: FakeCap(frames))
    k.start()
    fertig.wait(timeout=20)
    time.sleep(0.3)
    k.stop()
    assert len(aufnahmen) == 2
