import hashlib
import io
import json
import urllib.error

from labinett import update

INHALT = b"MZ neue exe"


def fake_netz(tag="v0.1.5", inhalt=INHALT, sha=None, assets=True):
    sha = sha or hashlib.sha256(inhalt).hexdigest()
    release = {"tag_name": tag, "assets": [
        {"name": "labinett.exe", "browser_download_url": "https://x/exe"},
        {"name": "labinett.exe.sha256", "browser_download_url": "https://x/sha"},
    ] if assets else []}
    daten = {update.API_LATEST: json.dumps(release).encode(), "https://x/exe": inhalt, "https://x/sha": f"{sha}\n".encode()}

    def oeffnen(req, timeout):
        return io.BytesIO(daten[req.full_url])

    return oeffnen


def test_versionen():
    assert update.version_tupel("v0.1.12") == (0, 1, 12)
    assert update.version_tupel("0.1.0.dev0") is None
    assert update.ist_neuer("v0.1.10", "0.1.9")
    assert not update.ist_neuer("v0.1.9", "0.1.9")
    assert not update.ist_neuer("v0.2.0", "0.1.3.dev7")  # Entwicklungsbuild nie aktualisieren


def test_neue_version_wird_geladen(tmp_path):
    exe = tmp_path / "labinett.exe"
    exe.write_bytes(b"alt")
    st = update.UpdateStatus()
    update.pruefen_und_laden(exe, "0.1.3", st, fake_netz())
    assert st.zustand == "bereit" and st.version == "0.1.5"
    assert (tmp_path / "labinett.exe.neu").read_bytes() == INHALT
    assert not (tmp_path / "labinett.exe.download").exists()


def test_schon_aktuell(tmp_path):
    exe = tmp_path / "labinett.exe"
    st = update.UpdateStatus()
    update.pruefen_und_laden(exe, "0.1.5", st, fake_netz())
    assert st.zustand == "aktuell"
    assert not (tmp_path / "labinett.exe.neu").exists()


def test_falsche_pruefsumme_verwirft(tmp_path):
    exe = tmp_path / "labinett.exe"
    st = update.UpdateStatus()
    update.pruefen_und_laden(exe, "0.1.3", st, fake_netz(sha="0" * 64))
    assert st.zustand == "fehler"
    assert list(tmp_path.iterdir()) == []


def test_ohne_netz_still(tmp_path):
    def offline(req, timeout):
        raise urllib.error.URLError("getaddrinfo failed")

    st = update.UpdateStatus()
    update.pruefen_und_laden(tmp_path / "labinett.exe", "0.1.3", st, offline)
    assert st.zustand == "offline"
    assert list(tmp_path.iterdir()) == []


def test_installieren_beim_start(tmp_path):
    exe = tmp_path / "labinett.exe"
    exe.write_bytes(b"alt")
    (tmp_path / "labinett.exe.neu").write_bytes(INHALT)
    gestartet = []
    assert update.bereit_installieren(exe, gestartet.append)
    assert exe.read_bytes() == INHALT and gestartet == [exe]
    assert (tmp_path / "labinett.exe.alt").read_bytes() == b"alt"
    # nächster Start räumt auf und startet normal
    assert not update.bereit_installieren(exe, gestartet.append)
    assert not (tmp_path / "labinett.exe.alt").exists()


def test_nicht_eingefroren_kein_update():
    assert update.exe_pfad() is None
    assert update.hintergrund_starten("0.1.3", update.UpdateStatus()) is None
