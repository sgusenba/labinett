import math

import pytest

from labinett.scheibe import FELD, POSITION, Geometrie, abstand_zum_feld, bewerte_schuss

# Feldgröße 15 mm, Loch 4,5 mm, Linie 0,4 mm -> Schwelle = 2,45/15 ≈ 0,163 Feldbreiten
GEO = Geometrie(feldgroesse_mm=15.0, lochdurchmesser_mm=4.5, linienbreite_mm=0.4, toleranz_mm=0.3)


def mitte(wert):
    i, j = POSITION[wert]
    return i + 0.5, j + 0.5


def test_matrix_ist_permutation():
    werte = sorted(w for zeile in FELD for w in zeile)
    assert werte == list(range(1, 26))


def test_spitzen():
    assert FELD[0][0] == 23 and FELD[4][0] == 25 and FELD[0][4] == 24 and FELD[4][4] == 22


def test_linien_nachbarn_von_16():
    i, j = POSITION[16]
    nachbarn = {FELD[i + di][j + dj] for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1))}
    assert nachbarn == {20, 10, 12, 1}


def test_volltreffer():
    t = bewerte_schuss(*mitte(16), GEO)
    assert t.felder == (16,) and t.wert == 16 and not t.anriss and not t.unsicher


def test_linie_16_12():
    # Grenze zwischen (1,2) und (1,3) liegt bei v = 3
    t = bewerte_schuss(1.5, 3.0, GEO)
    assert t.felder == (12, 16) and t.wert == 28 and t.anriss


def test_linie_1_14():
    t = bewerte_schuss(2.5, 3.0, GEO)
    assert t.wert == 15


def test_ecke_vier_felder():
    t = bewerte_schuss(2.0, 2.0, GEO)
    assert set(t.felder) == {10, 16, 17, 1} and t.wert == 44


def test_zeichnungs_nachbarn_nur_ueber_ecke():
    # 16 und 17 stehen in der Raute nebeneinander, teilen aber nur die Ecke (2,2)
    nahe_ecke = bewerte_schuss(2.0 - 0.05, 2.0 - 0.05, GEO)
    assert 16 in nahe_ecke.felder or 17 in nahe_ecke.felder
    an_linie_16_17 = bewerte_schuss(1.5, 2.5, GEO)  # Mitte 16, weit weg von 17
    assert 17 not in an_linie_16_17.felder


def test_nah_an_linie_ohne_beruehrung():
    s = GEO.schwelle
    # in 12 = (1,3), Abstand zur Grenze mit 8 = (0,3) bei u = 1 knapp über Schwelle + Toleranz
    t = bewerte_schuss(1.0 + s + GEO.toleranz + 0.01, 3.5, GEO)
    assert t.felder == (12,) and not t.unsicher


def test_grenzfall_wird_unsicher():
    t = bewerte_schuss(1.0 + GEO.schwelle + GEO.toleranz / 2, 3.5, GEO)
    assert t.felder == (12,) and t.unsicher


def test_aussen_randlinie_beruehrt():
    t = bewerte_schuss(-0.1, -0.1, GEO)
    assert t.felder == (23,)


def test_aussen_frei():
    t = bewerte_schuss(-1.0, 2.5, GEO)
    assert t.felder == () and t.wert == 0


def test_kartenbeispiel_71():
    schuesse = [mitte(16), (1.5, 3.0), mitte(12), mitte(1), mitte(14)]
    assert sum(bewerte_schuss(u, v, GEO).wert for u, v in schuesse) == 71


def test_abstand():
    assert abstand_zum_feld(0.5, 0.5, 0, 0) == 0
    assert math.isclose(abstand_zum_feld(1.3, 0.5, 0, 0), 0.3)
    assert math.isclose(abstand_zum_feld(1.3, 1.4, 0, 0), 0.5)


def test_geometrie_validierung():
    with pytest.raises(ValueError):
        Geometrie(feldgroesse_mm=0)


def test_anriss_toleranz_verschiebt_schwelle():
    from dataclasses import replace

    # Loch in 16 = (1,2), Rand 0,3 mm vor der Linie zu 12 (v = 3): zählt normal nicht
    v = 3 - GEO.schwelle - 0.3 / GEO.feldgroesse_mm
    assert bewerte_schuss(1.5, v, GEO).felder == (16,)
    # großzügiger: +0,5 mm -> Anriss
    assert bewerte_schuss(1.5, v, replace(GEO, anriss_toleranz_mm=0.5)).felder == (12, 16)
    # Loch knapp in der Linie: strenger (−0,5 mm) -> kein Anriss mehr
    v2 = 3 - GEO.schwelle + 0.2 / GEO.feldgroesse_mm
    assert bewerte_schuss(1.5, v2, GEO).felder == (12, 16)
    assert bewerte_schuss(1.5, v2, replace(GEO, anriss_toleranz_mm=-0.5)).felder == (16,)


def test_anriss_toleranz_nicht_unter_lochradius():
    with pytest.raises(ValueError):
        Geometrie(lochdurchmesser_mm=4.5, linienbreite_mm=0.0, anriss_toleranz_mm=-2.3)
