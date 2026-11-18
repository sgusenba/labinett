from pathlib import Path

from fastapi.testclient import TestClient

from labinett.app import erstelle_app
from labinett.config import Einstellungen

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"


def client(tmp_path):
    e = Einstellungen(csv_pfad=str(tmp_path / "erg.csv"), browser_oeffnen=False)
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
    assert c.post("/api/einstellungen", json={"feldgroesse_mm": "16"}).status_code == 200
    assert c.get("/api/einstellungen").json()["feldgroesse_mm"] == 16.0
    assert (tmp_path / "labinett.json").exists()
    assert c.post("/api/einstellungen", json={"feldgroesse_mm": "0"}).status_code == 400


def test_startseite(tmp_path):
    r = client(tmp_path).get("/")
    assert r.status_code == 200 and "labinett" in r.text
