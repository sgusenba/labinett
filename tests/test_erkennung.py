"""Erkennung auf echten Fotos (testdata/).

Referenz ist das handschriftlich auf der Karte notierte Ergebnis. Bei Karten,
deren Notizen widersprüchlich sind, wird nur die Anzahl der Schüsse geprüft.
"""

from pathlib import Path

import cv2
import pytest

from labinett.erkennung import erkenne, nummern_ausschnitt
from labinett.karte import werte_aus
from labinett.scheibe import Geometrie

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"
GEO = Geometrie(feldgroesse_mm=15.0, lochdurchmesser_mm=4.5, linienbreite_mm=0.4, toleranz_mm=0.5)


def auswerten(name):
    bild = cv2.imread(str(TESTDATA / name))
    assert bild is not None, name
    erk = erkenne(bild, GEO)
    return bild, erk, werte_aus(erk.positionen, GEO, "1")


@pytest.mark.parametrize(
    "name, gesamt, schusswerte",
    [
        ("nikolo_01.jpg", 104, [43, 13, 13, 13, 22]),
        ("nikolo_03.jpg", 162, [27, 53, 18, 13, 51]),
        ("nikolo_04.jpg", 147, [53, 13, 30, 29, 22]),
        ("nikolo_06.jpg", 71, [16, 28, 12, 1, 14]),
        # Karte 7: Kartenbox 98, Nebenrechnung links unten 131 – Erkennung entspricht 131
        ("nikolo_07.jpg", 131, [14, 33, 13, 20, 51]),
    ],
)
def test_gesamt_wie_auf_karte(name, gesamt, schusswerte):
    _, _, karte = auswerten(name)
    assert len(karte.schuesse) == 5
    assert karte.gesamt == gesamt
    assert sorted(s.wert for s in karte.schuesse) == sorted(schusswerte)


@pytest.mark.parametrize("name", ["nikolo_02.jpg", "nikolo_05.jpg"])
def test_widerspruechliche_karten_fuenf_schuesse(name):
    _, _, karte = auswerten(name)
    assert len(karte.schuesse) == 5


def test_nummern_ausschnitt_hat_kreis():
    bild, erk, _ = auswerten("nikolo_02.jpg")
    a = nummern_ausschnitt(bild, erk.ecken_bild)
    grau = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    kreise = cv2.HoughCircles(
        cv2.medianBlur(grau, 5), cv2.HOUGH_GRADIENT, 1.2, 100, param1=80, param2=30,
        minRadius=40, maxRadius=90,
    )
    assert kreise is not None
