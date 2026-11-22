"""Datenmodell einer ausgewerteten Karte."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from .scheibe import Geometrie, Treffer, bewerte_schuss

SCHUESSE_PRO_KARTE = 5

# Löcher aus einem aufgeteilten Fleck (überlappende Treffer) liegen ungenauer:
# auf den Testfotos streut ihr Mittelpunkt unter Drehung/Unschärfe/Auflösung bis
# 0,8 mm (einzelne Löcher bis 0,7 mm, 99 % unter 0,35 mm). Für sie gilt daher die
# doppelte Unsicherheits-Toleranz.
TOLERANZ_FAKTOR_GETEILT = 2.0


@dataclass
class Schuss:
    nr: int
    pos_u: float
    pos_v: float
    felder: tuple[int, ...]
    unsicher: bool

    @property
    def wert(self) -> int:
        return sum(self.felder)

    @property
    def anriss(self) -> bool:
        return len(self.felder) > 1

    def als_dict(self) -> dict:
        return {
            "nr": self.nr,
            "pos_u": round(self.pos_u, 4),
            "pos_v": round(self.pos_v, 4),
            "felder": list(self.felder),
            "wert": self.wert,
            "anriss": self.anriss,
            "unsicher": self.unsicher,
        }


@dataclass
class Karte:
    schuetzennummer: str | None
    nummer_quelle: str  # "auto" | "manuell" | "fehlt" | "aus" (Erfassung abgeschaltet)
    schuesse: list[Schuss]
    zeitstempel: datetime = field(default_factory=lambda: datetime.now().replace(microsecond=0))
    karten_uuid: str | None = None  # kommt später per QR
    bemerkung: str = ""
    # False: Schützennummer wird nicht erfasst, eine fehlende Nummer ist kein Prüfgrund
    nummer_pflicht: bool = True

    @property
    def gesamt(self) -> int:
        return sum(s.wert for s in self.schuesse)

    @property
    def gruende_pruefen(self) -> list[str]:
        gruende = []
        if len(self.schuesse) != SCHUESSE_PRO_KARTE:
            gruende.append(f"{len(self.schuesse)} statt {SCHUESSE_PRO_KARTE} Schüsse erkannt")
        unsicher = [str(s.nr) for s in self.schuesse if s.unsicher]
        if unsicher:
            gruende.append("unsicher: Schuss " + ", ".join(unsicher))
        if self.nummer_pflicht and not self.schuetzennummer:
            gruende.append("Schützennummer fehlt")
        return gruende

    @property
    def status(self) -> str:
        return "pruefen" if self.gruende_pruefen else "ok"

    def als_dict(self) -> dict:
        return {
            "zeitstempel": self.zeitstempel.isoformat(),
            "karten_uuid": self.karten_uuid,
            "schuetzennummer": self.schuetzennummer,
            "nummer_quelle": self.nummer_quelle,
            "schuesse": [s.als_dict() for s in self.schuesse],
            "gesamt": self.gesamt,
            "status": self.status,
            "gruende_pruefen": self.gruende_pruefen,
            "bemerkung": self.bemerkung,
        }


def werte_aus(
    positionen: list[tuple[float, float]],
    geo: Geometrie,
    schuetzennummer: str | None = None,
    nummer_quelle: str | None = None,
    karten_uuid: str | None = None,
    geteilt: list[bool] | None = None,
) -> Karte:
    """Wertet Lochmittelpunkte (Rasterkoordinaten) zu einer Karte aus.

    ``geteilt`` markiert je Position Löcher aus überlappenden Flecken; für sie
    gilt eine weitere Unsicherheits-Toleranz (``TOLERANZ_FAKTOR_GETEILT``).
    """
    geo_geteilt = replace(geo, toleranz_mm=geo.toleranz_mm * TOLERANZ_FAKTOR_GETEILT)
    schuesse = []
    for nr, (u, v) in enumerate(positionen, start=1):
        g = bool(geteilt and geteilt[nr - 1])
        t: Treffer = bewerte_schuss(u, v, geo_geteilt if g else geo)
        schuesse.append(Schuss(nr=nr, pos_u=u, pos_v=v, felder=t.felder, unsicher=t.unsicher))
    if nummer_quelle is None:
        nummer_quelle = "manuell" if schuetzennummer else "fehlt"
    return Karte(
        schuetzennummer=schuetzennummer,
        nummer_quelle=nummer_quelle,
        schuesse=schuesse,
        karten_uuid=karten_uuid,
    )
