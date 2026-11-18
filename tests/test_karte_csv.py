from labinett import csv_export
from labinett.karte import werte_aus
from labinett.scheibe import Geometrie

GEO = Geometrie(feldgroesse_mm=15.0, linienbreite_mm=0.4, toleranz_mm=0.3)
FUENF = [(1.5, 2.5), (1.5, 3.0), (1.5, 3.5), (2.5, 2.5), (2.5, 3.5)]  # 16, 16+12, 12, 1, 14


def test_karte_ok():
    k = werte_aus(FUENF, GEO, "7")
    assert k.gesamt == 71
    assert k.status == "ok" and k.nummer_quelle == "manuell"


def test_karte_zu_wenige_schuesse_und_ohne_nummer():
    k = werte_aus(FUENF[:4], GEO)
    assert k.status == "pruefen"
    assert any("4 statt 5" in g for g in k.gruende_pruefen)
    assert any("Schützennummer" in g for g in k.gruende_pruefen)


def test_csv_rundlauf(tmp_path):
    pfad = tmp_path / "unter" / "ergebnisse.csv"
    csv_export.anhaengen(pfad, werte_aus(FUENF, GEO, "7"))
    csv_export.anhaengen(pfad, werte_aus(FUENF[:4], GEO, "8"))
    roh = pfad.read_bytes()
    assert roh.startswith(b"\xef\xbb\xbf") and roh.count(b"\xef\xbb\xbf") == 1
    zeilen = csv_export.lesen(pfad)
    assert len(zeilen) == 2
    assert zeilen[0]["schuetzennummer"] == "7"
    assert zeilen[0]["s2_felder"] == "12+16" and zeilen[0]["s2_wert"] == "28"
    assert zeilen[0]["gesamt"] == "71" and zeilen[0]["status"] == "ok"
    assert zeilen[1]["s5_felder"] == "" and zeilen[1]["status"] == "pruefen"
    assert list(zeilen[0].keys()) == csv_export.SPALTEN
