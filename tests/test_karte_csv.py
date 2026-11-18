from labinett import csv_export
from labinett.karte import werte_aus
from labinett.scheibe import Geometrie

GEO = Geometrie(feldgroesse_mm=15.0, linienbreite_mm=0.4, toleranz_mm=0.3)
FUENF = [(1.5, 2.5), (1.5, 3.0), (1.5, 3.5), (2.5, 2.5), (2.5, 3.5)]  # 16, 16+12, 12, 1, 14


def test_karte_ok():
    k = werte_aus(FUENF, GEO, "7")
    assert k.gesamt == 71
    assert k.status == "ok" and k.nummer_quelle == "manuell"


def test_geteilte_loecher_haben_doppelte_toleranz():
    # 1,5 Toleranzen außerhalb der Berührungsschwelle zur Linie 16/12
    v = 3 - (GEO.schwelle + 1.5 * GEO.toleranz)
    einzeln = werte_aus([(1.5, v)], GEO)
    geteilt = werte_aus([(1.5, v)], GEO, geteilt=[True])
    assert einzeln.schuesse[0].felder == geteilt.schuesse[0].felder == (16,)
    assert not einzeln.schuesse[0].unsicher
    assert geteilt.schuesse[0].unsicher


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


# ------------------------------------------------ gesperrte Datei / Warteschlange

import pytest

from labinett import csv_export as ce


def _karte(nr="1"):
    return werte_aus(FUENF, GEO, nr)


def test_gesperrte_csv_landet_in_warteschlange(tmp_path, monkeypatch):
    csv_pfad, ws = tmp_path / "erg.csv", tmp_path / "ausstehend.jsonl"
    echt = ce._schreibe_zeilen

    def gesperrt(*a, **k):
        raise PermissionError(13, "Datei in Excel geöffnet")

    monkeypatch.setattr(ce, "_schreibe_zeilen", gesperrt)
    assert ce.speichern(csv_pfad, _karte("1"), ws) is False
    assert ce.speichern(csv_pfad, _karte("2"), ws) is False
    assert ce.ausstehend(ws) == 2 and not csv_pfad.exists()
    assert ce.nachtragen(csv_pfad, ws) == 2

    monkeypatch.setattr(ce, "_schreibe_zeilen", echt)
    assert ce.speichern(csv_pfad, _karte("3"), ws) is True
    assert [z["schuetzennummer"] for z in ce.lesen(csv_pfad)] == ["1", "2", "3"]
    assert ce.ausstehend(ws) == 0 and not ws.exists()


def test_nachtragen_ohne_neue_karte(tmp_path, monkeypatch):
    csv_pfad, ws = tmp_path / "erg.csv", tmp_path / "ausstehend.jsonl"
    echt = ce._schreibe_zeilen
    monkeypatch.setattr(ce, "_schreibe_zeilen", lambda *a, **k: (_ for _ in ()).throw(OSError("weg")))
    ce.speichern(csv_pfad, _karte("7"), ws)
    monkeypatch.setattr(ce, "_schreibe_zeilen", echt)
    assert ce.nachtragen(csv_pfad, ws) == 0
    assert ce.lesen(csv_pfad)[0]["schuetzennummer"] == "7"


def test_fremde_datei_wird_nicht_veraendert(tmp_path):
    fremd = tmp_path / "liste.csv"
    fremd.write_text("Name;Verein\nMaier;Bad Zell\n", encoding="utf-8")
    with pytest.raises(ce.FremdeDatei):
        ce.speichern(fremd, _karte(), tmp_path / "ws.jsonl")
    with pytest.raises(ce.FremdeDatei):
        ce.pruefe_ziel(fremd)
    assert fremd.read_text(encoding="utf-8") == "Name;Verein\nMaier;Bad Zell\n"


def test_pruefe_ziel_eigene_und_neue_datei(tmp_path):
    ce.pruefe_ziel(tmp_path / "neu" / "erg.csv")  # Ordner wird angelegt
    eigene = tmp_path / "erg.csv"
    ce.anhaengen(eigene, _karte())
    ce.pruefe_ziel(eigene)
    with pytest.raises(ce.FremdeDatei):
        ce.pruefe_ziel(tmp_path)
