"""Web-Oberfläche (FastAPI)."""

from __future__ import annotations

import base64
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import __version__, config, csv_export
from .erkennung import PX, RAND, Erkennung, ErkennungsFehler, erkenne, erkenne_nummer, nummern_ausschnitt
from .karte import Karte, Schuss, werte_aus
from .kamera import Kamera
from .scheibe import POSITION

STATIC = Path(__file__).parent / "static"


def _b64_jpeg(bild: np.ndarray, qualitaet: int = 85) -> str:
    ok, buf = cv2.imencode(".jpg", bild, [cv2.IMWRITE_JPEG_QUALITY, qualitaet])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else ""


def _markiere(normbild: np.ndarray, karte: Karte) -> np.ndarray:
    vis = cv2.cvtColor(normbild, cv2.COLOR_GRAY2BGR)
    for s in karte.schuesse:
        x = int(RAND * PX + s.pos_u * PX)
        y = int(RAND * PX + s.pos_v * PX)
        farbe = (0, 140, 255) if s.unsicher else ((0, 170, 0) if s.felder else (0, 0, 220))
        cv2.circle(vis, (x, y), 22, farbe, 3)
        cv2.putText(vis, str(s.nr), (x + 18, y - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.9, farbe, 2)
    # Darstellung wie auf der Karte: Raute auf der Spitze
    h, w = vis.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), -45, 1 / np.sqrt(2) * 1.15)
    return cv2.warpAffine(vis, M, (w, h), borderValue=(40, 40, 40))


def _signatur(karte: Karte) -> tuple:
    return tuple(sorted(s.felder for s in karte.schuesse))


def abstimmen(
    ergebnisse: list[tuple[np.ndarray, Erkennung, Karte]],
) -> tuple[np.ndarray, Erkennung, Karte, int]:
    """Mehrheit über mehrere Aufnahmen derselben Karte.

    Gewinnt das häufigste Ergebnis (bei Gleichstand das erste). Schüsse, deren
    Felder in einer abweichenden Aufnahme nicht vorkommen, werden als unsicher
    markiert. Gibt zusätzlich die Zahl der übereinstimmenden Aufnahmen zurück.
    """
    zaehler = Counter(_signatur(k) for _, _, k in ergebnisse)
    beste, anzahl = zaehler.most_common(1)[0]
    bild, erk, karte = next(r for r in ergebnisse if _signatur(r[2]) == beste)
    andere = [k for _, _, k in ergebnisse if _signatur(k) != beste]
    for s in karte.schuesse:
        if any(s.felder not in [t.felder for t in a.schuesse] for a in andere):
            s.unsicher = True
    return bild, erk, karte, anzahl


def _erkenne_alle(
    bilder: list[np.ndarray], geo, drehung: int
) -> tuple[list[tuple[np.ndarray, Erkennung]], ErkennungsFehler | None]:
    """Erkennung je Bild, parallel (OpenCV gibt den GIL frei). Reihenfolge bleibt erhalten."""

    def eins(bild: np.ndarray) -> Erkennung | ErkennungsFehler:
        try:
            return erkenne(bild, geo, drehung=drehung)
        except ErkennungsFehler as e:
            return e

    if len(bilder) == 1:
        erg = [eins(bilder[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(4, len(bilder))) as pool:
            erg = list(pool.map(eins, bilder))
    ok = [(b, e) for b, e in zip(bilder, erg) if isinstance(e, Erkennung)]
    fehler = next((e for e in erg if isinstance(e, ErkennungsFehler)), None)
    return ok, fehler


class Zustand:
    def __init__(self, einst: config.Einstellungen, warteschlange: Path) -> None:
        self.einst = einst
        self.warteschlange = warteschlange
        self.lock = threading.Lock()
        self.entwurf: dict | None = None
        self.entwurf_karte: Karte | None = None
        self.letzte_meldung = ""
        self.letzter_nachtrag = 0.0

    def auswerten(self, bilder: np.ndarray | list[np.ndarray], quelle: str) -> dict:
        """Wertet ein Bild oder mehrere Bilder derselben Karte aus (Mehrheit zählt)."""
        if isinstance(bilder, np.ndarray):
            bilder = [bilder]
        geo = self.einst.geometrie
        drehung = int(self.einst.extra.get("drehung", 0))
        erkannt, fehler = _erkenne_alle(bilder, geo, drehung)
        ergebnisse = [
            (bild, erk, werte_aus(erk.positionen, geo, geteilt=erk.geteilt)) for bild, erk in erkannt
        ]
        if not ergebnisse:
            raise HTTPException(422, str(fehler or "Kein Bild"))
        bild, erk, karte, einig = abstimmen(ergebnisse)
        hinweise = list(erk.hinweise)
        if einig < len(bilder):
            hinweise.append(
                f"nur {einig} von {len(bilder)} Aufnahmen stimmen überein – abweichende Schüsse markiert"
            )
        nummer_bild = None
        if self.einst.nummer_erfassen:
            ausschnitt = nummern_ausschnitt(bild, erk.ecken_bild)
            nummer = erkenne_nummer(ausschnitt)
            karte.schuetzennummer = nummer
            karte.nummer_quelle = "auto" if nummer else "fehlt"
            nummer_bild = _b64_jpeg(ausschnitt)
        else:
            karte.nummer_pflicht = False
            karte.nummer_quelle = "aus"
        entwurf = {
            "quelle": quelle,
            "karte": karte.als_dict(),
            "bild": _b64_jpeg(_markiere(erk.normbild, karte)),
            "nummer_bild": nummer_bild,
            "nummer_erfassen": self.einst.nummer_erfassen,
            "hinweise": hinweise,
        }
        with self.lock:
            self.entwurf = entwurf
            self.entwurf_karte = karte
        return entwurf


class SpeichernAnfrage(BaseModel):
    schuetzennummer: str = ""  # darf leer bleiben, wenn die Nummernerfassung aus ist
    felder: list[str] | None = None  # optional korrigiert, je Schuss z. B. "16+12"
    bemerkung: str = ""


class FokusAnfrage(BaseModel):
    wert: int  # ≥ 0 fester Fokus, -1 = Autofokus



def _speichern_unter_dialog(aktuell: Path) -> str | None:
    """Zeigt den Dateidialog des Betriebssystems; ``None`` bei Abbruch oder ohne Anzeige."""
    erg: list[str | None] = [None]

    def dialog() -> None:
        try:
            import tkinter
            from tkinter import filedialog

            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            pfad = filedialog.asksaveasfilename(
                parent=root,
                title="CSV-Datei für die Ergebnisse",
                initialdir=str(aktuell.parent),
                initialfile=aktuell.name,
                defaultextension=".csv",
                filetypes=[("CSV-Datei", "*.csv")],
                confirmoverwrite=False,  # vorhandene labinett-Datei wird fortgeschrieben
            )
            root.destroy()
            erg[0] = pfad or None
        except Exception:  # kein Display, kein tkinter
            erg[0] = None

    t = threading.Thread(target=dialog, daemon=True)
    t.start()
    t.join(timeout=300)
    return erg[0]


def _parse_felder(text: str) -> tuple[int, ...]:
    text = text.strip()
    if not text or text in ("0", "-"):
        return ()
    werte = []
    for teil in text.replace(",", "+").replace(" ", "+").split("+"):
        if not teil:
            continue
        w = int(teil)
        if w not in POSITION:
            raise HTTPException(400, f"Feld {w} gibt es nicht")
        werte.append(w)
    return tuple(sorted(werte))


def erstelle_app(
    einst: config.Einstellungen | None = None,
    mit_kamera: bool = True,
    config_pfad: Path | None = None,
) -> FastAPI:
    einst = einst or config.laden(config_pfad)
    ordner = config_pfad.parent if config_pfad else config.programm_ordner()
    zustand = Zustand(einst, ordner / "ausstehend.jsonl")
    app = FastAPI(title="labinett", version=__version__)
    app.state.zustand = zustand

    kamera: Kamera | None = None

    def bei_aufnahme(frames: list[np.ndarray]) -> None:
        with zustand.lock:
            if zustand.entwurf is not None:
                return  # offener Entwurf wird nicht überschrieben
        try:
            zustand.auswerten(frames, "auto")
        except HTTPException as e:
            zustand.letzte_meldung = str(e.detail)

    if mit_kamera:
        kamera = Kamera(
            einst.kamera_index,
            einst.kamera_breite,
            einst.kamera_hoehe,
            einst.stabile_frames,
            bei_aufnahme,
            aufnahme_bilder=einst.aufnahme_bilder,
            toleranz_rel=einst.stabil_toleranz,
            sperren=einst.kamera_festhalten,
            fokus=einst.kamera_fokus,
            mjpg=einst.kamera_mjpg,
        )

        @app.on_event("startup")
        def _start() -> None:
            kamera.start()

        @app.on_event("shutdown")
        def _stop() -> None:
            kamera.stop()

    app.state.kamera = kamera

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/stream.mjpg")
    def stream() -> StreamingResponse:
        if kamera is None:
            raise HTTPException(404, "Keine Kamera aktiv")

        def gen():
            while True:
                jpg = kamera.vorschau_jpeg()
                if jpg:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                time.sleep(0.1)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    def nachtragen() -> tuple[int, str]:
        """Ausstehende CSV-Zeilen schreiben (höchstens alle 3 s versuchen)."""
        offen = csv_export.ausstehend(zustand.warteschlange)
        if not offen:
            return 0, ""
        if time.monotonic() - zustand.letzter_nachtrag < 3:
            return offen, ""
        zustand.letzter_nachtrag = time.monotonic()
        try:
            return csv_export.nachtragen(einst.csv_datei(), zustand.warteschlange), ""
        except csv_export.FremdeDatei as e:
            return offen, str(e)

    @app.get("/api/status")
    def status() -> dict:
        with zustand.lock:
            entwurf = zustand.entwurf
            offen, csv_fehler = nachtragen()
        return {
            "version": __version__,
            "kamera": kamera.status() if kamera else {"kamera_ok": False, "fehler": "deaktiviert"},
            "entwurf": entwurf,
            "meldung": zustand.letzte_meldung,
            "csv": str(einst.csv_datei()),
            "csv_ausstehend": offen,
            "csv_fehler": csv_fehler,
        }

    @app.post("/api/aufnehmen")
    def aufnehmen() -> dict:
        if kamera is None or not (frames := kamera.frames()):
            raise HTTPException(409, "Kein Kamerabild verfügbar")
        return zustand.auswerten(frames, "manuell")

    @app.post("/api/kamera/treiber")
    def kamera_treiber() -> dict:
        if kamera is None:
            raise HTTPException(409, "Keine Kamera aktiv")
        kamera.treiber_dialog()
        return {"ok": True}

    @app.post("/api/kamera/fokus")
    def kamera_fokus(anfrage: FokusAnfrage) -> dict:
        """Fokus sofort ändern (-1 = Autofokus neu scharfstellen) und als Einstellung merken."""
        if not -1 <= anfrage.wert <= 4095:
            raise HTTPException(400, "Fokuswert muss zwischen -1 und 4095 liegen")
        if kamera is None:
            raise HTTPException(409, "Keine Kamera aktiv")
        kamera.fokus_setzen(anfrage.wert)
        einst.kamera_fokus = anfrage.wert
        config.speichern(einst, config_pfad)
        return {"ok": True, "fokus": anfrage.wert}

    @app.post("/api/bild")
    async def bild(datei: UploadFile = File(...)) -> dict:
        daten = np.frombuffer(await datei.read(), np.uint8)
        img = cv2.imdecode(daten, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, "Datei ist kein lesbares Bild")
        return zustand.auswerten(img, f"datei:{datei.filename}")

    @app.post("/api/speichern")
    def speichern(anfrage: SpeichernAnfrage) -> dict:
        with zustand.lock:
            karte = zustand.entwurf_karte
            if karte is None:
                raise HTTPException(409, "Keine Karte zum Speichern")
            nummer = anfrage.schuetzennummer.strip()
            if not nummer and karte.nummer_pflicht:
                raise HTTPException(400, "Schützennummer fehlt")
            if nummer:
                if not nummer.isdigit() or not einst.nummer_min <= int(nummer) <= einst.nummer_max:
                    raise HTTPException(
                        400, f"Schützennummer muss zwischen {einst.nummer_min} und {einst.nummer_max} liegen"
                    )
                nummer = str(int(nummer))  # führende Nullen weg
            korrigiert = False
            if anfrage.felder is not None:
                neue = []
                for i, text in enumerate(anfrage.felder):
                    f = _parse_felder(text)
                    alt = karte.schuesse[i] if i < len(karte.schuesse) else None
                    if alt is None or f != alt.felder:
                        korrigiert = True
                    neue.append(
                        Schuss(
                            nr=i + 1,
                            pos_u=alt.pos_u if alt else float("nan"),
                            pos_v=alt.pos_v if alt else float("nan"),
                            felder=f,
                            unsicher=False,  # vom Bediener bestätigt
                        )
                    )
                karte.schuesse = neue
            else:
                for s in karte.schuesse:
                    s.unsicher = False  # Bediener hat Entwurf bestätigt
            if nummer and karte.schuetzennummer != nummer:
                karte.schuetzennummer = nummer
                karte.nummer_quelle = "manuell"
            teile = [anfrage.bemerkung.strip()]
            if korrigiert:
                teile.append("manuell korrigiert")
            karte.bemerkung = "; ".join(t for t in teile if t)
            try:
                in_csv = csv_export.speichern(einst.csv_datei(), karte, zustand.warteschlange)
            except csv_export.FremdeDatei as e:
                raise HTTPException(409, str(e)) from e
            ergebnis = karte.als_dict()
            ergebnis["csv_gespeichert"] = in_csv
            ergebnis["csv_ausstehend"] = csv_export.ausstehend(zustand.warteschlange)
            zustand.entwurf = None
            zustand.entwurf_karte = None
        return ergebnis

    @app.post("/api/verwerfen")
    def verwerfen() -> dict:
        with zustand.lock:
            zustand.entwurf = None
            zustand.entwurf_karte = None
        return {"ok": True}

    @app.get("/api/ergebnisse")
    def ergebnisse(anzahl: int = 20) -> list[dict]:
        pfad = einst.csv_datei()
        if not pfad.exists():
            return []
        return list(reversed(csv_export.lesen(pfad)[-anzahl:]))

    @app.get("/api/einstellungen")
    def einstellungen_lesen() -> dict:
        return asdict(einst)

    @app.post("/api/einstellungen")
    def einstellungen_schreiben(neu: dict) -> JSONResponse:
        erlaubt = {k for k in config.Einstellungen.__dataclass_fields__ if k != "extra"}
        geaendert = {}
        try:
            for k, v in neu.items():
                if k in erlaubt:
                    geaendert[k] = config.wert_umwandeln(getattr(einst, k), v)
            probe = config.Einstellungen(**{**asdict(einst), **geaendert})
            probe.pruefe()
        except (ValueError, TypeError) as e:
            raise HTTPException(400, f"Ungültiger Wert: {e}") from e
        if "csv_pfad" in geaendert and probe.csv_datei() != einst.csv_datei():
            try:
                csv_export.pruefe_ziel(probe.csv_datei())
            except csv_export.FremdeDatei as e:
                raise HTTPException(400, str(e)) from e
            except OSError as e:
                raise HTTPException(400, f"In {probe.csv_datei().parent} kann nicht geschrieben werden ({e.strerror or e})") from e
        for k, v in geaendert.items():
            setattr(einst, k, v)
        config.speichern(einst, config_pfad)
        return JSONResponse({"ok": True, "hinweis": "Gespeichert. Kamera-Einstellungen wirken nach Neustart."})

    @app.post("/api/csv-dialog")
    def csv_dialog() -> dict:
        """Windows-Dialog „Speichern unter“ öffnen (läuft lokal auf dem Auswerte-PC)."""
        return {"pfad": _speichern_unter_dialog(einst.csv_datei())}

    return app
