"""Web-Oberfläche (FastAPI)."""

from __future__ import annotations

import base64
import threading
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import __version__, config, csv_export
from .erkennung import PX, RAND, ErkennungsFehler, erkenne, erkenne_nummer, nummern_ausschnitt
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


class Zustand:
    def __init__(self, einst: config.Einstellungen) -> None:
        self.einst = einst
        self.lock = threading.Lock()
        self.entwurf: dict | None = None
        self.entwurf_karte: Karte | None = None
        self.letzte_meldung = ""

    def auswerten(self, bild: np.ndarray, quelle: str) -> dict:
        geo = self.einst.geometrie
        try:
            erk = erkenne(bild, geo, drehung=int(self.einst.extra.get("drehung", 0)))
        except ErkennungsFehler as e:
            raise HTTPException(422, str(e)) from e
        ausschnitt = nummern_ausschnitt(bild, erk.ecken_bild)
        nummer = erkenne_nummer(ausschnitt)
        karte = werte_aus(
            erk.positionen, geo, nummer, nummer_quelle="auto" if nummer else "fehlt"
        )
        entwurf = {
            "quelle": quelle,
            "karte": karte.als_dict(),
            "bild": _b64_jpeg(_markiere(erk.normbild, karte)),
            "nummer_bild": _b64_jpeg(ausschnitt),
            "hinweise": erk.hinweise,
        }
        with self.lock:
            self.entwurf = entwurf
            self.entwurf_karte = karte
        return entwurf


class SpeichernAnfrage(BaseModel):
    schuetzennummer: str
    felder: list[str] | None = None  # optional korrigiert, je Schuss z. B. "16+12"
    bemerkung: str = ""


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
    zustand = Zustand(einst)
    app = FastAPI(title="labinett", version=__version__)
    app.state.zustand = zustand

    kamera: Kamera | None = None

    def bei_aufnahme(frame: np.ndarray) -> None:
        with zustand.lock:
            if zustand.entwurf is not None:
                return  # offener Entwurf wird nicht überschrieben
        try:
            zustand.auswerten(frame, "auto")
        except HTTPException as e:
            zustand.letzte_meldung = str(e.detail)

    if mit_kamera:
        kamera = Kamera(
            einst.kamera_index,
            einst.kamera_breite,
            einst.kamera_hoehe,
            einst.stabile_frames,
            bei_aufnahme,
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

    @app.get("/api/status")
    def status() -> dict:
        with zustand.lock:
            entwurf = zustand.entwurf
        return {
            "version": __version__,
            "kamera": kamera.status() if kamera else {"kamera_ok": False, "fehler": "deaktiviert"},
            "entwurf": entwurf,
            "meldung": zustand.letzte_meldung,
            "csv": str(einst.csv_datei()),
        }

    @app.post("/api/aufnehmen")
    def aufnehmen() -> dict:
        if kamera is None or (frame := kamera.frame()) is None:
            raise HTTPException(409, "Kein Kamerabild verfügbar")
        return zustand.auswerten(frame, "manuell")

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
            if not nummer:
                raise HTTPException(400, "Schützennummer fehlt")
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
            if karte.schuetzennummer != nummer:
                karte.schuetzennummer = nummer
                karte.nummer_quelle = "manuell"
            teile = [anfrage.bemerkung.strip()]
            if korrigiert:
                teile.append("manuell korrigiert")
            karte.bemerkung = "; ".join(t for t in teile if t)
            csv_export.anhaengen(einst.csv_datei(), karte)
            ergebnis = karte.als_dict()
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
                    geaendert[k] = type(getattr(einst, k))(v)
            config.Einstellungen(**{**asdict(einst), **geaendert}).geometrie  # validiert
        except (ValueError, TypeError) as e:
            raise HTTPException(400, f"Ungültiger Wert: {e}") from e
        for k, v in geaendert.items():
            setattr(einst, k, v)
        config.speichern(einst, config_pfad)
        return JSONResponse({"ok": True, "hinweis": "Kamera-Einstellungen wirken nach Neustart"})

    return app
