"""Auto-Aufnahme mit simulierter Kamera."""

import threading
import time
from pathlib import Path

import cv2
import numpy as np

from labinett.erkennung import schnell_ecken
from labinett.kamera import Kamera, ecken_ruhig

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"


class FakeCap:
    def __init__(self, frames):
        self.frames = frames
        self.i = 0
        self.gesetzt = {}

    def isOpened(self):
        return True

    def read(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        time.sleep(0.005)
        return True, f

    def get(self, prop):
        return 42.0

    def set(self, prop, wert):
        self.gesetzt[prop] = wert
        return True

    def release(self):
        pass


def test_schnell_ecken_findet_raute():
    bild = cv2.imread(str(TESTDATA / "nikolo_04.jpg"))
    assert schnell_ecken(bild) is not None


def test_ecken_ruhig_relativ_zur_diagonale():
    a = np.array([[500, 0], [1000, 500], [500, 1000], [0, 500]], float)
    assert ecken_ruhig(a, a + [9, 0], 0.01)  # 9 px bei 1000 px Diagonale: ruhig
    assert not ecken_ruhig(a, a + [12, 0], 0.01)
    assert not ecken_ruhig(a, None, 0.01)


def _laufen(frames, warte_s=20, **kw):
    aufnahmen = []
    fertig = threading.Event()

    def bei_aufnahme(bilder):
        aufnahmen.append(bilder)
        if len(aufnahmen) == 2:
            fertig.set()

    k = Kamera(0, 640, 480, stabile_frames=5, bei_aufnahme=bei_aufnahme, **kw)
    cap = FakeCap(frames)
    k._oeffnen = lambda: cap
    k.start()
    fertig.wait(timeout=warte_s)
    time.sleep(0.3)
    k.stop()
    return aufnahmen, k, cap


def test_auto_aufnahme_einmal_pro_karte():
    karte = cv2.imread(str(TESTDATA / "nikolo_04.jpg"))
    leer = karte.copy()
    leer[:] = 30
    # Karte liegt 15 Frames, wird entfernt (10 leere), wieder hingelegt (15)
    frames = [karte] * 15 + [leer] * 10 + [karte] * 15 + [leer] * 200
    aufnahmen, _, _ = _laufen(frames, aufnahme_bilder=3, sperren=False)
    assert len(aufnahmen) == 2
    # jede Aufnahme liefert die letzten 3 ruhigen Bilder
    assert all(len(a) == 3 and a[0].shape == karte.shape for a in aufnahmen)


def test_kamera_werte_festhalten(monkeypatch):
    karte = cv2.imread(str(TESTDATA / "nikolo_04.jpg"))
    monkeypatch.setattr(Kamera, "EINLAUF_S", 0.0)
    _, k, cap = _laufen([karte] * 20, warte_s=1.5, sperren=True, fokus=17)
    assert cap.gesetzt[cv2.CAP_PROP_AUTOFOCUS] == 0
    assert cap.gesetzt[cv2.CAP_PROP_FOCUS] == 17
    assert cap.gesetzt[cv2.CAP_PROP_EXPOSURE] == 42.0
    assert k.status()["festgehalten"]["fokus"] is True


def test_fokus_live_setzen(monkeypatch):
    karte = cv2.imread(str(TESTDATA / "nikolo_04.jpg"))
    monkeypatch.setattr(Kamera, "EINLAUF_S", 0.0)
    k = Kamera(0, 640, 480, stabile_frames=5, bei_aufnahme=lambda b: None, sperren=True)
    cap = FakeCap([karte] * 2000)
    k._oeffnen = lambda: cap
    k.start()
    try:
        time.sleep(0.3)
        k.fokus_setzen(120)
        time.sleep(0.3)
        assert cap.gesetzt[cv2.CAP_PROP_AUTOFOCUS] == 0
        assert cap.gesetzt[cv2.CAP_PROP_FOCUS] == 120
        assert k.status()["autofokus"] is False
        assert k.status()["fokus"] == 42.0  # FakeCap meldet immer 42
        # Autofokus: kurz wieder an, danach (Einlauf 0 s) erneut festgehalten
        cap.gesetzt.clear()
        k.fokus_setzen(-1)
        time.sleep(0.3)
        assert k.fokus == -1
        assert cap.gesetzt[cv2.CAP_PROP_AUTOFOCUS] == 0  # nach dem Einlauf wieder fest
        assert cap.gesetzt[cv2.CAP_PROP_FOCUS] == 42.0  # eingeregelter Wert übernommen
    finally:
        k.stop()


def test_vorschau_nur_neue_bilder():
    import numpy as np

    from labinett.kamera import Kamera

    k = Kamera(0, 640, 480, 3, lambda f: None)
    assert k.vorschau() is None
    k._frame = np.zeros((480, 640, 3), np.uint8)
    k._frame_nr = 1
    nr, jpg = k.vorschau()
    assert nr == 1 and jpg[:2] == b"\xff\xd8"
    assert k.vorschau(nach=1) is None  # kein neues Bild -> nichts senden
    assert k.vorschau(nach=0) == (1, jpg)  # zweiter Zuseher bekommt das schon kodierte Bild
