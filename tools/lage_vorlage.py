"""Vorlage für die Lageerkennung bauen → labinett/modelle/raster_vorlage.png

Median der entzerrten Feldzahlen (``erkennung.ziffern_tinte``) über alle
aufrecht liegenden Testfotos in testdata/. Der Median blendet die Einschusslöcher
der einzelnen Karten aus.

    python tools/lage_vorlage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
from labinett import erkennung as E  # noqa: E402


def main() -> None:
    tinten = []
    for f in sorted((WURZEL / "testdata").glob("*.jpg")):
        grau = cv2.cvtColor(cv2.imread(str(f)), cv2.COLOR_BGR2GRAY)
        ecken = E._ecken(E._finde_gitter_maske(grau))  # Testfotos liegen aufrecht
        tinten.append(E.ziffern_tinte(grau, ecken))
    v = np.median(tinten, axis=0)
    cv2.imwrite(str(E.VORLAGE), np.round(v / v.max() * 255).astype(np.uint8))
    print(f"{E.VORLAGE} aus {len(tinten)} Fotos")


if __name__ == "__main__":
    main()
