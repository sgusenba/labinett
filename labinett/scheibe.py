"""Geometrie und Wertung der Nikolo-Glücksscheibe.

Koordinatensystem (Rasterkoordinaten, Einheit = eine Feldbreite):
- Ursprung ist die obere Spitze der Raute (Feld 23).
- Die u-Achse (Index i) zeigt nach rechts unten Richtung Feld 25.
- Die v-Achse (Index j) zeigt nach links unten Richtung Feld 24.
- Feld (i, j) belegt das Quadrat [i, i+1) x [j, j+1).

Die Umrechnung vom Kamerabild in diese Koordinaten (Homographie) ist nicht Teil
dieses Moduls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RASTER = 5

# Feste Maße – nicht einstellbar
KARTE_MM = 170.0  # Karte 170 × 170 mm, Format der Standard-Luftpistolenscheibe (ISSF 10 m)
KALIBER_MM = 4.5  # Lochdurchmesser: es wird immer Kaliber 4,5 mm geschossen
# Kantenlänge eines Feldes. Aus den Testfotos über die Kartengröße ermittelt:
# die Karte ist 10,5–10,6 Feldbreiten lang → 170 mm / 10,6 ≈ 16,0 mm (Raster 80 × 80 mm).
FELD_MM = 16.0

# FELD[i][j] – aufgedruckter Wert des Feldes (i, j)
FELD: tuple[tuple[int, ...], ...] = (
    (23, 5, 20, 8, 24),
    (4, 10, 16, 12, 6),
    (19, 17, 1, 14, 21),
    (2, 11, 15, 13, 9),
    (25, 3, 18, 7, 22),
)

# Rückwärtssuche: Wert -> (i, j)
POSITION: dict[int, tuple[int, int]] = {
    FELD[i][j]: (i, j) for i in range(RASTER) for j in range(RASTER)
}


@dataclass(frozen=True)
class Geometrie:
    """Physische Maße der Scheibe. Alle Längen in Millimetern.

    Feldgröße und Lochdurchmesser sind durch Karte und Kaliber fest vorgegeben
    (siehe ``FELD_MM``, ``KALIBER_MM``); sie bleiben hier nur für Tests änderbar.
    """

    feldgroesse_mm: float = FELD_MM
    lochdurchmesser_mm: float = KALIBER_MM
    linienbreite_mm: float = 0.0
    toleranz_mm: float = 0.5  # so nah an der Schwelle wird ein Schuss als unsicher markiert
    # Anriss-Toleranz: verschiebt die Berührungsschwelle. Negativ = strenger (das Loch
    # muss tiefer in die Linie reichen), positiv = großzügiger (knapp daneben zählt schon).
    anriss_toleranz_mm: float = 0.0

    def __post_init__(self) -> None:
        if self.feldgroesse_mm <= 0:
            raise ValueError("feldgroesse_mm muss > 0 sein")
        if self.lochdurchmesser_mm <= 0:
            raise ValueError("lochdurchmesser_mm muss > 0 sein")
        if self.linienbreite_mm < 0 or self.toleranz_mm < 0:
            raise ValueError("linienbreite_mm und toleranz_mm dürfen nicht negativ sein")
        if self.lochdurchmesser_mm / 2 + self.linienbreite_mm / 2 + self.anriss_toleranz_mm <= 0:
            raise ValueError("anriss_toleranz_mm ist kleiner als der Lochradius")

    @property
    def schwelle(self) -> float:
        """Berührungsschwelle in Feldeinheiten: Lochradius + halbe Linienbreite + Anriss-Toleranz."""
        return (
            self.lochdurchmesser_mm / 2 + self.linienbreite_mm / 2 + self.anriss_toleranz_mm
        ) / self.feldgroesse_mm

    @property
    def toleranz(self) -> float:
        """Unsicherheitsband in Feldeinheiten."""
        return self.toleranz_mm / self.feldgroesse_mm


@dataclass(frozen=True)
class Treffer:
    felder: tuple[int, ...]  # aufsteigend nach Wert sortiert
    unsicher: bool

    @property
    def wert(self) -> int:
        return sum(self.felder)

    @property
    def anriss(self) -> bool:
        return len(self.felder) > 1


def feld_wert(i: int, j: int) -> int:
    if not (0 <= i < RASTER and 0 <= j < RASTER):
        raise IndexError(f"Feld ({i}, {j}) liegt außerhalb des Rasters")
    return FELD[i][j]


def abstand_zum_feld(u: float, v: float, i: int, j: int) -> float:
    """Euklidischer Abstand eines Punktes zum Feldquadrat (0, wenn innen)."""
    du = max(i - u, 0.0, u - (i + 1))
    dv = max(j - v, 0.0, v - (j + 1))
    return math.hypot(du, dv)


def bewerte_schuss(u: float, v: float, geo: Geometrie) -> Treffer:
    """Ermittelt alle Felder, die ein Loch mit Mittelpunkt (u, v) berührt.

    Ein Feld zählt, wenn der Abstand vom Lochmittelpunkt zum Feldquadrat
    höchstens Lochradius + halbe Linienbreite + Anriss-Toleranz beträgt. Liegt ein Abstand
    innerhalb der Toleranz um diese Schwelle, ist der Schuss unsicher.
    """
    s = geo.schwelle
    t = geo.toleranz
    reichweite = s + t

    i_min = max(0, math.floor(u - reichweite))
    i_max = min(RASTER - 1, math.floor(u + reichweite))
    j_min = max(0, math.floor(v - reichweite))
    j_max = min(RASTER - 1, math.floor(v + reichweite))

    felder: list[int] = []
    unsicher = False
    for i in range(i_min, i_max + 1):
        for j in range(j_min, j_max + 1):
            d = abstand_zum_feld(u, v, i, j)
            if d <= s:
                felder.append(FELD[i][j])
            if abs(d - s) <= t:
                unsicher = True
    return Treffer(felder=tuple(sorted(felder)), unsicher=unsicher)
