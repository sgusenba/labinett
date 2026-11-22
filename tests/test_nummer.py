"""Schützennummer lesen.

Echte Karten (testdata/*.jpg) tragen alle die Nummer 1 oder keine. Mehrstellige
Nummern prüfen synthetische Kreise (testdata/nummern/): MNIST-Testziffern (nicht im
Training), als dünne Tinte in echte leere Kreise der Webcam-Fotos geschrieben,
Dateiname = Sollnummer. Oberstes Ziel: nie eine falsche Nummer vorschlagen.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from labinett import nummer as N
from labinett.erkennung import erkenne, nummern_ausschnitt
from labinett.scheibe import Geometrie

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"
MIT_EINS = [
    "nikolo_01.jpg", "nikolo_02.jpg", "nikolo_03.jpg", "nikolo_04.jpg", "nikolo_05.jpg",
    "nikolo_06.jpg", "nikolo_07.jpg",
    *(f"WIN_20261118_20_{t}_Pro.jpg" for t in ("17_53", "18_05", "18_20", "18_29", "18_41")),
]
LEER = [f"WIN_20261118_20_{t}_Pro.jpg" for t in ("18_51", "19_03", "19_22")]
SYNTHETISCH = sorted((TESTDATA / "nummern").glob("*.jpg"))


def ausschnitt(name):
    bild = cv2.imread(str(TESTDATA / name))
    return nummern_ausschnitt(bild, erkenne(bild, Geometrie()).ecken_bild)


def test_modell_vorhanden():
    assert N.MODELL.exists()
    p = N.klassifiziere([np.zeros((28, 28), np.float32)])
    assert p.shape == (1, N.KEINE_ZIFFER + 1)


@pytest.mark.parametrize("name", MIT_EINS)
def test_echte_karten_eins(name):
    lesung = N.lies_nummer(ausschnitt(name))
    assert [z for z, _ in lesung.ziffern] == [1]
    assert lesung.nummer in ("1", None)


def test_echte_karten_meist_sicher():
    sicher = [N.lies_nummer(ausschnitt(n)).nummer for n in MIT_EINS]
    assert sicher.count("1") >= len(MIT_EINS) * 0.75


@pytest.mark.parametrize("name", LEER)
def test_leerer_kreis(name):
    lesung = N.lies_nummer(ausschnitt(name))
    assert lesung.nummer is None and lesung.ziffern == []


def test_synthetische_nummern():
    assert len(SYNTHETISCH) >= 30
    richtig = falsch = 0
    for p in SYNTHETISCH:
        soll = p.stem.split("_")[0]
        ist = N.lies_nummer(cv2.imread(str(p))).nummer
        richtig += ist == soll
        falsch += ist is not None and ist != soll
    # bekannt: 137_14 liest „131“ – die MNIST-7 ist dort nur ein Strich mit Häkchen.
    # Synthetisch (600 Kreise): 82 % richtig, 17 % offen, 1 % falsch – mehr Fehler sind ein Rückschritt.
    assert falsch <= 1
    assert richtig >= 0.75 * len(SYNTHETISCH)


def test_bereich_wird_beachtet():
    lesung = N.lies_nummer(ausschnitt("nikolo_02.jpg"), nummer_min=2, nummer_max=250)
    assert lesung.nummer is None


def test_normiere_mnist_format():
    m = np.zeros((60, 30), np.uint8)
    cv2.line(m, (15, 3), (15, 56), 255, 2)
    z = N.normiere(m)
    assert z.shape == (28, 28) and z.max() <= 1.0
    ys, xs = np.nonzero(z > 0.5)
    assert 18 <= ys.max() - ys.min() + 1 <= 20  # längere Seite ≈ 20 px
    assert abs(xs.mean() - 14) < 1.5 and abs(ys.mean() - 14) < 1.5
    # Strichstärke wird angeglichen: dünn und dick ergeben fast dasselbe Bild
    dick = np.zeros_like(m)
    cv2.line(dick, (15, 3), (15, 56), 255, 7)
    assert np.abs(N.normiere(dick) - z).mean() < 0.05


def L(nummer, ziffern=((1, 0.9),), grund=""):
    return N.Lesung(nummer, list(ziffern), grund)


def test_abstimmen():
    assert N.abstimmen([L("12"), L("12"), L(None)]).nummer == "12"
    assert N.abstimmen([L("12"), L(None), L(None)]).nummer is None
    uneinig = N.abstimmen([L("12"), L("13"), L("12")])
    assert uneinig.nummer is None and "uneinig" in uneinig.grund
    assert N.abstimmen([L("7")]).nummer == "7"
