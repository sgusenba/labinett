from pathlib import Path

from fastapi.testclient import TestClient

from labinett.app import erstelle_app
from labinett.config import Einstellungen

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"


def client(tmp_path):
    # Nummernerfassung ist standardmäßig aus; die meisten Tests prüfen sie mit
    e = Einstellungen(csv_pfad=str(tmp_path / "erg.csv"), browser_oeffnen=False, nummer_erfassen=True)
    return TestClient(erstelle_app(e, mit_kamera=False, config_pfad=tmp_path / "labinett.json"))


def test_foto_auswerten_und_speichern(tmp_path):
    c = client(tmp_path)
    with open(TESTDATA / "nikolo_04.jpg", "rb") as f:
        r = c.post("/api/bild", files={"datei": ("nikolo_04.jpg", f, "image/jpeg")})
    assert r.status_code == 200, r.text
    entwurf = r.json()
    assert entwurf["karte"]["gesamt"] == 147
    assert entwurf["bild"].startswith("data:image/jpeg")
    assert c.get("/api/status").json()["entwurf"] is not None

    # ohne Nummer nicht speichern
    assert c.post("/api/speichern", json={"schuetzennummer": " "}).status_code == 400

    r = c.post("/api/speichern", json={"schuetzennummer": "12"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    rows = c.get("/api/ergebnisse").json()
    assert rows[0]["schuetzennummer"] == "12" and rows[0]["gesamt"] == "147"
    assert c.get("/api/status").json()["entwurf"] is None


def test_manuelle_korrektur(tmp_path):
    c = client(tmp_path)
    with open(TESTDATA / "nikolo_06.jpg", "rb") as f:
        c.post("/api/bild", files={"datei": ("x.jpg", f, "image/jpeg")})
    felder = ["16", "16+12", "12", "1", "14"]
    r = c.post("/api/speichern", json={"schuetzennummer": "3", "felder": felder})
    assert r.status_code == 200
    assert r.json()["gesamt"] == 71
    bad = c.post("/api/bild", files={"datei": ("x.txt", b"kein bild", "text/plain")})
    assert bad.status_code == 400


def test_ungueltiges_feld(tmp_path):
    c = client(tmp_path)
    with open(TESTDATA / "nikolo_01.jpg", "rb") as f:
        c.post("/api/bild", files={"datei": ("x.jpg", f, "image/jpeg")})
    r = c.post("/api/speichern", json={"schuetzennummer": "1", "felder": ["26", "", "", "", ""]})
    assert r.status_code == 400


def test_einstellungen(tmp_path):
    c = client(tmp_path)
    assert c.post("/api/einstellungen", json={"linienbreite_mm": "0.3"}).status_code == 200
    assert c.get("/api/einstellungen").json()["linienbreite_mm"] == 0.3
    assert (tmp_path / "labinett.json").exists()
    assert c.post("/api/einstellungen", json={"toleranz_mm": "-1"}).status_code == 400
    # Feldgröße und Kaliber sind fest und lassen sich nicht verstellen
    c.post("/api/einstellungen", json={"feldgroesse_mm": "20", "lochdurchmesser_mm": "6"})
    e = c.get("/api/einstellungen").json()
    assert "feldgroesse_mm" not in e and "lochdurchmesser_mm" not in e


def test_startseite(tmp_path):
    r = client(tmp_path).get("/")
    assert r.status_code == 200 and "labinett" in r.text


# ------------------------------------------------ Nummer, CSV-Sperre, Einstellungen, Abstimmung

import cv2
import pytest

from labinett import csv_export


def _foto(c, name="nikolo_04.jpg"):
    with open(TESTDATA / name, "rb") as f:
        r = c.post("/api/bild", files={"datei": (name, f, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("nummer", ["0", "251", "abc", "12a", "-3"])
def test_nummer_ausserhalb_1_bis_250(tmp_path, nummer):
    c = client(tmp_path)
    _foto(c)
    r = c.post("/api/speichern", json={"schuetzennummer": nummer})
    assert r.status_code == 400 and "1 und 250" in r.json()["detail"]
    assert c.get("/api/status").json()["entwurf"] is not None  # Entwurf bleibt


def test_nummer_fuehrende_nullen(tmp_path):
    c = client(tmp_path)
    _foto(c)
    assert c.post("/api/speichern", json={"schuetzennummer": "007"}).json()["schuetzennummer"] == "7"


def test_gesperrte_csv_wird_nachgetragen(tmp_path, monkeypatch):
    c = client(tmp_path)
    echt = csv_export._schreibe_zeilen

    def gesperrt(*a, **k):
        raise PermissionError(13, "gesperrt")

    monkeypatch.setattr(csv_export, "_schreibe_zeilen", gesperrt)
    _foto(c)
    r = c.post("/api/speichern", json={"schuetzennummer": "5"}).json()
    assert r["csv_gespeichert"] is False and r["csv_ausstehend"] == 1
    assert c.get("/api/status").json()["csv_ausstehend"] == 1

    monkeypatch.setattr(csv_export, "_schreibe_zeilen", echt)
    c.app.state.zustand.letzter_nachtrag = 0
    assert c.get("/api/status").json()["csv_ausstehend"] == 0
    assert c.get("/api/ergebnisse").json()[0]["schuetzennummer"] == "5"


def test_csv_pfad_fremde_datei_abgelehnt(tmp_path):
    c = client(tmp_path)
    fremd = tmp_path / "fremd.csv"
    fremd.write_text("a;b\n1;2\n", encoding="utf-8")
    r = c.post("/api/einstellungen", json={"csv_pfad": str(fremd)})
    assert r.status_code == 400 and "nicht verändert" in r.json()["detail"]
    neu = tmp_path / "unter" / "nikolo.csv"
    assert c.post("/api/einstellungen", json={"csv_pfad": str(neu)}).status_code == 200
    _foto(c)
    c.post("/api/speichern", json={"schuetzennummer": "9"})
    assert neu.exists()


def test_einstellungen_ja_nein_und_bereich(tmp_path):
    c = client(tmp_path)
    assert c.post("/api/einstellungen", json={"kamera_festhalten": "false"}).status_code == 200
    assert c.get("/api/einstellungen").json()["kamera_festhalten"] is False
    assert c.post("/api/einstellungen", json={"nummer_min": "300"}).status_code == 400


def test_abstimmung_ueber_mehrere_bilder(tmp_path):
    c = client(tmp_path)
    z = c.app.state.zustand
    a = cv2.imread(str(TESTDATA / "nikolo_04.jpg"))
    b = cv2.imread(str(TESTDATA / "nikolo_06.jpg"))
    e = z.auswerten([a, a, a], "test")
    assert e["karte"]["gesamt"] == 147 and not any("Aufnahmen" in h for h in e["hinweise"])
    e = z.auswerten([a, b, a], "test")  # ein Ausreißer
    assert e["karte"]["gesamt"] == 147
    assert any("2 von 3" in h for h in e["hinweise"])
    assert e["karte"]["status"] == "pruefen"


def test_nummer_vorschlag_und_sammeln(tmp_path):
    c = client(tmp_path)
    with open(TESTDATA / "nikolo_03.jpg", "rb") as f:
        entwurf = c.post("/api/bild", files={"datei": ("k.jpg", f, "image/jpeg")}).json()
    karte = entwurf["karte"]
    # Vorschlag ist entweder die richtige 1 oder leer – nie etwas anderes
    assert karte["schuetzennummer"] in ("1", None)
    assert karte["nummer_quelle"] == ("auto" if karte["schuetzennummer"] else "fehlt")
    r = c.post("/api/speichern", json={"schuetzennummer": "1"})
    assert r.status_code == 200
    gesammelt = list((tmp_path / "nummern").glob("1_*.png"))
    assert len(gesammelt) == 1


def test_nummer_lesen_abschaltbar(tmp_path):
    e = Einstellungen(csv_pfad=str(tmp_path / "erg.csv"), browser_oeffnen=False, nummer_lesen=False, nummern_sammeln=False)
    c = TestClient(erstelle_app(e, mit_kamera=False, config_pfad=tmp_path / "labinett.json"))
    with open(TESTDATA / "nikolo_03.jpg", "rb") as f:
        karte = c.post("/api/bild", files={"datei": ("k.jpg", f, "image/jpeg")}).json()["karte"]
    assert karte["schuetzennummer"] is None
    assert c.post("/api/speichern", json={"schuetzennummer": "1"}).status_code == 200
    assert not (tmp_path / "nummern").exists()


def test_fokus_endpunkt(tmp_path):
    c = client(tmp_path)
    assert c.post("/api/kamera/fokus", json={"wert": -5}).status_code == 400
    assert c.post("/api/kamera/fokus", json={"wert": 100}).status_code == 409  # ohne Kamera


def test_fokus_endpunkt_mit_kamera(tmp_path, monkeypatch):
    from labinett import app as app_mod
    from labinett import config

    gesetzt = []

    class FakeKamera:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def fokus_setzen(self, w):
            gesetzt.append(w)

    monkeypatch.setattr(app_mod, "Kamera", FakeKamera)
    e = Einstellungen(csv_pfad=str(tmp_path / "erg.csv"), browser_oeffnen=False)
    c = TestClient(erstelle_app(e, mit_kamera=True, config_pfad=tmp_path / "labinett.json"))
    assert c.post("/api/kamera/fokus", json={"wert": 80}).status_code == 200
    assert c.post("/api/kamera/fokus", json={"wert": -1}).status_code == 200
    assert gesetzt == [80, -1]
    assert config.laden(tmp_path / "labinett.json").kamera_fokus == -1


def test_ohne_schuetzennummer(tmp_path):
    e = Einstellungen(csv_pfad=str(tmp_path / "erg.csv"), browser_oeffnen=False)  # Standard: aus
    c = TestClient(erstelle_app(e, mit_kamera=False, config_pfad=tmp_path / "labinett.json"))
    with open(TESTDATA / "nikolo_04.jpg", "rb") as f:
        entwurf = c.post("/api/bild", files={"datei": ("x.jpg", f, "image/jpeg")}).json()
    assert entwurf["nummer_erfassen"] is False and entwurf["nummer_bild"] is None
    assert entwurf["karte"]["status"] == "ok"  # fehlende Nummer ist kein Prüfgrund
    r = c.post("/api/speichern", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok" and r.json()["nummer_quelle"] == "aus"
    zeile = c.get("/api/ergebnisse").json()[0]
    assert zeile["schuetzennummer"] == "" and zeile["gesamt"] == "147"


def test_nummernerfassung_live_abschalten(tmp_path):
    c = client(tmp_path)
    assert c.post("/api/einstellungen", json={"nummer_erfassen": False}).status_code == 200
    with open(TESTDATA / "nikolo_01.jpg", "rb") as f:
        c.post("/api/bild", files={"datei": ("x.jpg", f, "image/jpeg")})
    # Nummer darf trotzdem angegeben werden, wird dann geprüft
    assert c.post("/api/speichern", json={"schuetzennummer": "999"}).status_code == 400
    assert c.post("/api/speichern", json={"schuetzennummer": "8"}).json()["schuetzennummer"] == "8"


def test_anriss_toleranz_wertet_entwurf_neu(tmp_path):
    c = client(tmp_path)
    with open(TESTDATA / "nikolo_06.jpg", "rb") as f:
        alt = c.post("/api/bild", files={"datei": ("x.jpg", f, "image/jpeg")}).json()["karte"]
    assert alt["gesamt"] == 71
    r = c.post("/api/anriss-toleranz", json={"wert": 0.8})
    assert r.status_code == 200, r.text
    neu = r.json()["entwurf"]["karte"]
    assert neu["zeitstempel"] == alt["zeitstempel"]  # gleicher Entwurf, nur neu gewertet
    assert neu["gesamt"] == 86  # großzügiger: ein weiteres Loch zählt als Anriss
    assert c.get("/api/einstellungen").json()["anriss_toleranz_mm"] == 0.8
    assert c.get("/api/entwurf").json()["karte"]["gesamt"] == 86
    streng = c.post("/api/anriss-toleranz", json={"wert": -0.8}).json()["entwurf"]["karte"]
    assert streng["gesamt"] == 55
    zurueck = c.post("/api/anriss-toleranz", json={"wert": 0}).json()["entwurf"]["karte"]
    assert zurueck["gesamt"] == 71
    assert c.post("/api/anriss-toleranz", json={"wert": 5}).status_code == 400
    assert c.post("/api/einstellungen", json={"anriss_toleranz_mm": "-3"}).status_code == 400
    # gespeichert wird der neu gewertete Entwurf
    c.post("/api/anriss-toleranz", json={"wert": 0.8})
    assert c.post("/api/speichern", json={"schuetzennummer": "7"}).json()["gesamt"] == 86


def test_anriss_toleranz_ohne_entwurf(tmp_path):
    r = client(tmp_path).post("/api/anriss-toleranz", json={"wert": -0.2})
    assert r.status_code == 200 and r.json()["entwurf"] is None
