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
    # Karte liegt 15 Frames, wird entfernt (100 leere, > LEER_MIN_S), wieder hingelegt (15)
    frames = [karte] * 15 + [leer] * 100 + [karte] * 15 + [leer] * 200
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


def test_kurzes_verschwinden_ist_keine_entnahme():
    """Raute kurz nicht erkannt (z. B. Hand, Reflex), Karte liegt aber noch: keine 2. Aufnahme."""
    karte = cv2.imread(str(TESTDATA / "nikolo_04.jpg"))
    verdeckt = karte.copy()
    verdeckt[:, :800] = (90, 110, 150)  # Hand über der linken Hälfte, Raute nicht mehr erkennbar
    assert schnell_ecken(verdeckt) is None
    entnahmen = []
    frames = [karte] * 15 + [verdeckt] * 120 + [karte] * 200
    k = Kamera(0, 640, 480, stabile_frames=5, bei_aufnahme=lambda b: None, sperren=False,
               bei_entnahme=lambda: entnahmen.append(1))
    aufnahmen = []
    k.bei_aufnahme = aufnahmen.append
    cap = FakeCap(frames)
    k._oeffnen = lambda: cap
    k.start()
    while cap.i < len(frames):
        time.sleep(0.05)
    k.stop()
    assert len(aufnahmen) == 1 and entnahmen == []


def test_entnahme_wird_gemeldet():
    karte = cv2.imread(str(TESTDATA / "nikolo_04.jpg"))
    leer = karte.copy()
    leer[:] = 30
    entnahmen = []
    frames = [karte] * 15 + [leer] * 150
    k = Kamera(0, 640, 480, stabile_frames=5, bei_aufnahme=lambda b: None, sperren=False,
               bei_entnahme=lambda: entnahmen.append(1))
    cap = FakeCap(frames)
    k._oeffnen = lambda: cap
    k.start()
    while cap.i < len(frames):
        time.sleep(0.05)
    k.stop()
    assert entnahmen == [1] and k.status()["entnahmen"] == 1
    assert not k.status()["wartet_auf_neue_karte"]


def test_naechste_belichtung():
    from labinett.kamera import naechste_belichtung

    assert naechste_belichtung(-5, dunkler=True) == -6  # DirectShow: log2-Sekunden
    assert naechste_belichtung(-5, dunkler=False) == -4
    assert naechste_belichtung(-13, dunkler=True) == -13
    assert naechste_belichtung(300, dunkler=True) == 210  # V4L2: 100 µs
    assert naechste_belichtung(1, dunkler=True) == 1


class HelleCap(FakeCap):
    """Kamera, deren Bild ab Belichtung > -6 ausbrennt (Ringlicht an)."""

    def __init__(self, karte):
        super().__init__([karte])
        self.karte = karte
        self.exp = -3.0

    def read(self):
        time.sleep(0.005)
        if self.exp > -6:
            return True, cv2.convertScaleAbs(self.karte, alpha=3.0)
        return True, self.karte

    def get(self, prop):
        return self.exp if prop == cv2.CAP_PROP_EXPOSURE else 42.0

    def set(self, prop, wert):
        if prop == cv2.CAP_PROP_EXPOSURE:
            self.exp = wert
        return super().set(prop, wert)


def test_belichtung_wird_bei_ueberbelichtung_reduziert(monkeypatch):
    monkeypatch.setattr(Kamera, "EINLAUF_S", 0.0)
    karte = cv2.imread(str(TESTDATA / "nikolo_04.jpg"))
    cap = HelleCap(karte)
    k = Kamera(0, 640, 480, stabile_frames=5, bei_aufnahme=lambda b: None, sperren=True)
    k._oeffnen = lambda: cap
    k.start()
    try:
        ende = time.monotonic() + 10
        while cap.exp > -6 and time.monotonic() < ende:
            time.sleep(0.05)
        time.sleep(0.5)
    finally:
        k.stop()
    assert cap.exp == -6  # bis knapp unter die Ausbrenn-Grenze abgedunkelt, nicht weiter
    assert k.status()["belichtung"] == -6
