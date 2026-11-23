"""Erkennung auf echten Fotos (testdata/).

Referenz ist das handschriftlich auf der Karte notierte Ergebnis. Weicht die
Handwertung nur bei Grenzfällen ab, muss die Erkennung genau diese Schüsse als
unsicher markieren. ``nikolo_*`` sind Handyfotos, ``WIN_*`` Webcam-Aufnahmen
(1920 × 1080), teils von denselben Karten.
"""

from pathlib import Path

import cv2
import pytest

from labinett.erkennung import erkenne, nummern_ausschnitt
from labinett.karte import werte_aus
from labinett.scheibe import Geometrie

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"
GEO = Geometrie(linienbreite_mm=0.4, toleranz_mm=0.5)  # Feldgröße 16 mm, Kaliber 4,5 mm fest


def auswerten(name):
    bild = cv2.imread(str(TESTDATA / name))
    assert bild is not None, name
    erk = erkenne(bild, GEO)
    return bild, erk, werte_aus(erk.positionen, GEO, "1", geteilt=erk.geteilt)


WEBCAM = "WIN_20261118_20_{}_Pro.jpg".format


@pytest.mark.parametrize(
    "name, gesamt, schusswerte",
    [
        ("nikolo_01.jpg", 104, [43, 13, 13, 13, 22]),
        ("nikolo_03.jpg", 162, [27, 53, 18, 13, 51]),
        ("nikolo_04.jpg", 147, [53, 13, 30, 29, 22]),
        ("nikolo_06.jpg", 71, [16, 28, 12, 1, 14]),
        # Karte 7: Kartenbox 98, Nebenrechnung links unten 131 – Erkennung entspricht 131
        ("nikolo_07.jpg", 131, [14, 33, 13, 20, 51]),
        # Webcam
        (WEBCAM("18_20"), 104, [43, 13, 13, 13, 22]),  # Karte von nikolo_01
        (WEBCAM("18_05"), 147, [53, 13, 30, 29, 22]),  # Karte von nikolo_04
        (WEBCAM("18_41"), 131, [14, 33, 13, 20, 51]),  # Karte von nikolo_07
        (WEBCAM("18_51"), 59, [10, 10, 12, 1, 26]),
        # ohne Handwertung, Felder am Foto nachgezählt; Schuss 5+10+16 ist ein Grenzfall
        (WEBCAM("19_03"), 94, [31, 16, 17, 16, 14]),
        # Box sagt 85, richtig ist 83 (bestätigt)
        (WEBCAM("19_22"), 83, [36, 17, 1, 15, 14]),
    ],
)
def test_gesamt_wie_auf_karte(name, gesamt, schusswerte):
    _, _, karte = auswerten(name)
    assert len(karte.schuesse) == 5
    assert karte.gesamt == gesamt
    assert sorted(s.wert for s in karte.schuesse) == sorted(schusswerte)


@pytest.mark.parametrize(
    "name, hand",
    [
        # Notizen 43, 28, 53, 13, 1 = 138: zwei Löcher berühren laut Hand die Linie knapp mehr
        ("nikolo_02.jpg", [43, 28, 53, 13, 1]),
        (WEBCAM("17_53"), [43, 28, 53, 13, 1]),
        # Notizen 53, 15+13+7, 13, 13, 22 = 136: Eckschuss ohne die 18
        ("nikolo_05.jpg", [53, 35, 13, 13, 22]),
        (WEBCAM("18_29"), [53, 35, 13, 13, 22]),
    ],
)
def test_abweichung_zur_handwertung_nur_bei_unsicheren_schuessen(name, hand):
    _, _, karte = auswerten(name)
    assert len(karte.schuesse) == 5
    assert karte.status == "pruefen"
    rest = list(hand)
    for s in karte.schuesse:
        if not s.unsicher:
            assert s.wert in rest, (s.nr, s.felder)
            rest.remove(s.wert)


@pytest.mark.parametrize(
    "webcam, handy",
    [("17_53", "nikolo_02.jpg"), ("18_05", "nikolo_04.jpg"), ("18_20", "nikolo_01.jpg"),
     ("18_29", "nikolo_05.jpg"), ("18_41", "nikolo_07.jpg")],
)
def test_webcam_und_handy_liefern_gleiche_lochlagen(webcam, handy):
    """Gleiche Karte, andere Kamera: Lochmittelpunkte stimmen auf 0,5 mm überein."""
    a = sorted(auswerten(WEBCAM(webcam))[1].positionen)
    b = sorted(auswerten(handy)[1].positionen)
    assert len(a) == len(b) == 5
    for (ua, va), (ub, vb) in zip(a, b):
        assert max(abs(ua - ub), abs(va - vb)) * GEO.feldgroesse_mm < 0.5


@pytest.mark.parametrize("name", [WEBCAM("18_51"), WEBCAM("18_05")])
@pytest.mark.parametrize("stoerung", ["drehung", "720p", "unschaerfe", "dunkel"])
def test_webcam_robust(name, stoerung):
    """Leichte Drehung, 720p, Unschärfe und schwaches Licht ändern das Ergebnis nicht."""
    bild = cv2.imread(str(TESTDATA / name))
    h, w = bild.shape[:2]
    if stoerung == "drehung":
        M = cv2.getRotationMatrix2D((w / 2, h / 2), 5, 1.0)
        bild = cv2.warpAffine(bild, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    elif stoerung == "720p":
        bild = cv2.resize(bild, (1280, 720), interpolation=cv2.INTER_AREA)
    elif stoerung == "unschaerfe":
        bild = cv2.GaussianBlur(bild, (0, 0), 1.5)
    else:
        bild = (bild * 0.6).astype(bild.dtype)
    ref = sorted(s.wert for s in auswerten(name)[2].schuesse)
    erk = erkenne(bild, GEO)
    assert sorted(s.wert for s in werte_aus(erk.positionen, GEO).schuesse) == ref


def test_nummern_ausschnitt_hat_kreis():
    bild, erk, _ = auswerten("nikolo_02.jpg")
    a = nummern_ausschnitt(bild, erk.ecken_bild)
    grau = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    kreise = cv2.HoughCircles(
        cv2.medianBlur(grau, 5), cv2.HOUGH_GRADIENT, 1.2, 100, param1=80, param2=30,
        minRadius=40, maxRadius=90,
    )
    assert kreise is not None


# ------------------------------------------------ feste Kartengröße

from labinett.erkennung import KARTE_FELDER, kartengroesse_abweichung, kartenseiten_felder  # noqa: E402
from labinett.scheibe import FELD_MM, KALIBER_MM, KARTE_MM  # noqa: E402


def test_feste_masse():
    assert KARTE_MM == 170.0 and KALIBER_MM == 4.5 and FELD_MM == 16.0
    g = Geometrie()
    assert g.feldgroesse_mm == FELD_MM and g.lochdurchmesser_mm == KALIBER_MM


def test_kartengroesse_passt_zum_raster():
    """Auf Foto 07 liegt die ganze Karte im Bild: sie muss ~170 mm / 16 mm Feldbreiten lang sein."""
    bild = cv2.imread(str(TESTDATA / "nikolo_07.jpg"))
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    erk = erkenne(bild, GEO)
    seiten = kartenseiten_felder(grau, erk.ecken_bild)
    assert seiten is not None
    assert sum(seiten) / 4 == pytest.approx(KARTE_FELDER, rel=0.03)
    assert kartengroesse_abweichung(grau, erk.ecken_bild) < 0.08
    assert not any("Kartengröße" in h for h in erk.hinweise)


def test_angeschnittene_karte_wird_nicht_gemessen():
    bild = cv2.imread(str(TESTDATA / "nikolo_02.jpg"))  # oben angeschnitten
    erk = erkenne(bild, GEO)
    assert kartenseiten_felder(cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY), erk.ecken_bild) is None


# ------------------------------------------------ Lage der Karte

from labinett.erkennung import LAGE_MIN_ABSTAND, VORLAGE, _ecken, _finde_gitter_maske, _lage  # noqa: E402

DREHUNGEN = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def test_vorlage_liegt_bei():
    assert VORLAGE.exists()


@pytest.mark.parametrize("grad", [90, 180, 270])
@pytest.mark.parametrize("name", [WEBCAM("18_05"), WEBCAM("19_22"), "nikolo_07.jpg"])
def test_gedrehte_karte_gleiches_ergebnis(name, grad):
    """Karte verdreht hingelegt: Feld 23 wird gefunden, Schusswerte bleiben gleich."""
    bild = cv2.imread(str(TESTDATA / name))
    ref = auswerten(name)[1]
    erk = erkenne(cv2.rotate(bild, DREHUNGEN[grad]), GEO)
    assert not any("Lage" in h for h in erk.hinweise)
    for (u, v), (ur, vr) in zip(sorted(erk.positionen), sorted(ref.positionen)):
        assert max(abs(u - ur), abs(v - vr)) * GEO.feldgroesse_mm < 0.5
    karte = werte_aus(erk.positionen, GEO, geteilt=erk.geteilt)
    ref_karte = werte_aus(ref.positionen, GEO, geteilt=ref.geteilt)
    assert sorted(s.wert for s in karte.schuesse) == sorted(s.wert for s in ref_karte.schuesse)


@pytest.mark.parametrize("name", sorted(p.name for p in TESTDATA.glob("*.jpg")))
def test_lage_aller_testfotos_eindeutig(name):
    grau = cv2.cvtColor(cv2.imread(str(TESTDATA / name)), cv2.COLOR_BGR2GRAY)
    for grad, rot in [(0, None), *DREHUNGEN.items()]:
        g = grau if rot is None else cv2.rotate(grau, rot)
        k, abstand = _lage(g, _ecken(_finde_gitter_maske(g)))
        assert k == grad // 90, grad
        assert abstand > 2 * LAGE_MIN_ABSTAND
