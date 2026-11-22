"""Synthetische Nummernkreise für die Tests → testdata/nummern/<nummer>_<i>.jpg

MNIST-*Test*ziffern (nicht im Training) als dünne Tinte in die echten leeren
Nummernkreise der Webcam-Fotos schreiben. Echte Karten tragen bisher nur die
Nummer 1; mehrstellige Nummern lassen sich so trotzdem prüfen.

    python tools/nummern_testsatz.py mnist.npz [--anzahl 40]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
from labinett import nummer as N  # noqa: E402
from labinett.erkennung import erkenne, nummern_ausschnitt  # noqa: E402
from labinett.scheibe import Geometrie  # noqa: E402

LEER = [f"WIN_20261118_20_{t}_Pro.jpg" for t in ("18_51", "19_03", "19_22")]


def leere_kreise() -> list[np.ndarray]:
    aus = []
    for n in LEER:
        b = cv2.imread(str(WURZEL / "testdata" / n))
        aus.append(nummern_ausschnitt(b, erkenne(b, Geometrie()).ecken_bild))
    return aus


def schreibe(hinter: np.ndarray, ziffern: list[np.ndarray], rng: np.random.Generator) -> np.ndarray | None:
    a = hinter.astype(np.float32).copy()
    H, W = a.shape[:2]
    hoehe = rng.uniform(*{1: (40, 62), 2: (36, 56), 3: (30, 44)}[len(ziffern)])
    duenn = rng.random() < 0.5
    teile = []
    for z in ziffern:
        ys, xs = np.nonzero(z > 30)
        m = z[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1].astype(np.float32) / 255
        f = hoehe * rng.uniform(0.9, 1.05) / m.shape[0]
        t = cv2.resize(m, (max(2, round(m.shape[1] * f)), max(2, round(m.shape[0] * f))), interpolation=cv2.INTER_CUBIC)
        t = np.clip((t - 0.35) * 2.2, 0, 1)
        if duenn:
            t = cv2.erode(t, np.ones((2, 2), np.uint8))
        teile.append(t)
    abstand = rng.uniform(1, 6)
    breite = sum(t.shape[1] for t in teile) + abstand * (len(teile) - 1)
    g = cv2.cvtColor(hinter, cv2.COLOR_BGR2GRAY)
    bh = cv2.morphologyEx(cv2.GaussianBlur(g, (3, 3), 0), cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    kx, ky, kr = N._kreis(g, bh)
    if breite > 1.45 * kr:
        return None
    cx, cy = kx + rng.uniform(-5, 5), ky + rng.uniform(-5, 5)
    x = cx - breite / 2
    farbe = np.array(rng.choice([[120, 60, 30], [90, 50, 40], [60, 60, 60]]), np.float32) * rng.uniform(0.7, 1.3)
    deckung = rng.uniform(0.5, 1.0)
    for t in teile:
        h, w = t.shape
        y0, x0 = int(cy - h / 2 + rng.uniform(-3, 3)), int(x)
        if y0 < 0 or x0 < 0 or y0 + h > H or x0 + w > W:
            return None
        alpha = (t * deckung)[..., None]
        a[y0 : y0 + h, x0 : x0 + w] = a[y0 : y0 + h, x0 : x0 + w] * (1 - alpha) + farbe * alpha
        x += w + abstand
    a = cv2.GaussianBlur(a, (0, 0), rng.uniform(0.3, 0.9))
    a += rng.normal(0, 2, a.shape)
    return np.clip(a, 0, 255).astype(np.uint8)


def erzeuge(mnist: Path, anzahl: int, seed: int) -> list[tuple[str, np.ndarray]]:
    d = dict(np.load(mnist, allow_pickle=False))
    x, y = d["x_test"], d["y_test"]
    nach = {k: np.nonzero(y == k)[0] for k in range(10)}
    rng = np.random.default_rng(seed)
    kreise = leere_kreise()
    faelle: list[tuple[str, np.ndarray]] = []
    while len(faelle) < anzahl:
        nr = str(int(rng.integers(1, 251)))
        a = schreibe(kreise[len(faelle) % len(kreise)], [x[rng.choice(nach[int(c)])] for c in nr], rng)
        if a is not None:
            faelle.append((nr, a))
    return faelle


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mnist", type=Path)
    ap.add_argument("--anzahl", type=int, default=40)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--ziel", type=Path, default=WURZEL / "testdata" / "nummern")
    a = ap.parse_args()
    a.ziel.mkdir(parents=True, exist_ok=True)
    for i, (nr, bild) in enumerate(erzeuge(a.mnist, a.anzahl, a.seed)):
        cv2.imwrite(str(a.ziel / f"{nr}_{i:02d}.jpg"), bild, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(a.anzahl, "Kreise in", a.ziel)


if __name__ == "__main__":
    main()
