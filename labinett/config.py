"""Konfiguration: labinett.json neben dem Programm (bzw. im Arbeitsverzeichnis)."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .scheibe import Geometrie


def programm_ordner() -> Path:
    """Ordner der .exe bei PyInstaller-Builds, sonst das Arbeitsverzeichnis."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


@dataclass
class Einstellungen:
    csv_pfad: str = "ergebnisse.csv"
    kamera_index: int = 0
    kamera_breite: int = 1920
    kamera_hoehe: int = 1080
    port: int = 8765
    browser_oeffnen: bool = True
    # Feldgröße (16 mm) und Kaliber (4,5 mm) sind fest, siehe scheibe.py.
    # Einstellbar bleiben nur Druckstärke der Linien und Unsicherheits-Band.
    linienbreite_mm: float = 0.4
    toleranz_mm: float = 0.5
    # Auto-Aufnahme: so viele aufeinanderfolgende stabile Frames
    stabile_frames: int = 8
    # Ruhig = keine Rautenecke bewegt sich mehr als dieser Anteil der Diagonale
    stabil_toleranz: float = 0.01
    # So viele ruhige Frames werden ausgewertet und abgestimmt
    aufnahme_bilder: int = 3
    # Autofokus, Belichtung, Weißabgleich nach dem Start festhalten
    kamera_festhalten: bool = True
    # Fester Fokuswert (kameraabhängig), -1 = eingeregelten Wert übernehmen
    kamera_fokus: int = -1
    # Gültige Schützennummern
    nummer_min: int = 1
    nummer_max: int = 250
    # Handschriftliche Nummer automatisch lesen (Vorschlag, Bediener bestätigt mit Enter)
    nummer_lesen: bool = True
    # Bestätigte Nummern-Ausschnitte in „nummern/“ ablegen, um das Modell nachzutrainieren
    nummern_sammeln: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def geometrie(self) -> Geometrie:
        return Geometrie(
            linienbreite_mm=self.linienbreite_mm,
            toleranz_mm=self.toleranz_mm,
        )

    def csv_datei(self, basis: Path | None = None) -> Path:
        p = Path(self.csv_pfad)
        return p if p.is_absolute() else (basis or programm_ordner()) / p

    def pruefe(self) -> None:
        """Wirft ValueError bei unsinnigen Werten."""
        self.geometrie  # noqa: B018 – validiert die Maße
        if not 1 <= self.nummer_min <= self.nummer_max:
            raise ValueError("Nummernbereich ungültig")
        if self.stabile_frames < 1 or self.aufnahme_bilder < 1:
            raise ValueError("Frames müssen mindestens 1 sein")
        if not 0 < self.stabil_toleranz < 0.2:
            raise ValueError("Ruhe-Toleranz muss zwischen 0 und 0,2 liegen")


def wert_umwandeln(alt: object, neu: object) -> object:
    """Wert aus der Oberfläche in den Typ der Einstellung bringen (auch "false" → False)."""
    if isinstance(alt, bool):
        if isinstance(neu, str):
            t = neu.strip().lower()
            if t in ("1", "true", "ja", "on"):
                return True
            if t in ("0", "false", "nein", "off", ""):
                return False
            raise ValueError(f"kein Ja/Nein-Wert: {neu!r}")
        return bool(neu)
    return type(alt)(neu)


def laden(pfad: Path | None = None) -> Einstellungen:
    pfad = pfad or programm_ordner() / "labinett.json"
    if not pfad.exists():
        e = Einstellungen()
        speichern(e, pfad)
        return e
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    bekannt = {k: v for k, v in daten.items() if k in Einstellungen.__dataclass_fields__}
    return Einstellungen(**bekannt)


def speichern(e: Einstellungen, pfad: Path | None = None) -> None:
    pfad = pfad or programm_ordner() / "labinett.json"
    pfad.write_text(json.dumps(asdict(e), indent=2, ensure_ascii=False), encoding="utf-8")
