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
    # Physische Maße – Feldgröße aus Testfotos geschätzt (ca. 15 mm), bitte nachmessen
    feldgroesse_mm: float = 15.0
    lochdurchmesser_mm: float = 4.5
    linienbreite_mm: float = 0.4
    toleranz_mm: float = 0.5
    # Auto-Aufnahme: so viele aufeinanderfolgende stabile Frames
    stabile_frames: int = 8
    extra: dict = field(default_factory=dict)

    @property
    def geometrie(self) -> Geometrie:
        return Geometrie(
            feldgroesse_mm=self.feldgroesse_mm,
            lochdurchmesser_mm=self.lochdurchmesser_mm,
            linienbreite_mm=self.linienbreite_mm,
            toleranz_mm=self.toleranz_mm,
        )

    def csv_datei(self, basis: Path | None = None) -> Path:
        p = Path(self.csv_pfad)
        return p if p.is_absolute() else (basis or programm_ordner()) / p


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
