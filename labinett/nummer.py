"""Handschriftliche Schützennummer im Kreis links oben lesen.

Ablauf
1. Kreis im Ausschnitt suchen (Hough), nur das Innere betrachten.
2. Tinte = deutlich dunkler als das Papier ringsum (Black-Hat), Rauschen weg.
3. Striche zu Ziffern gruppieren (überlappende Spalten = eine Ziffer), links → rechts.
4. Jede Ziffer wie MNIST normieren (``normiere``): Strichstärke angleichen,
   in 20 × 20 einpassen, Schwerpunkt in die Mitte eines 28 × 28-Bilds.
5. Kleines CNN (``modelle/ziffern.onnx``, über OpenCV-DNN, kein Torch nötig).

Die Nummer wird nur zurückgegeben, wenn jede Ziffer sicher erkannt ist und die
Zahl im gültigen Bereich liegt; sonst ``None`` und die Nummer wird eingetippt.
Das Netz trainiert ``tools/ziffern_trainieren.py`` mit derselben Normierung.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

MODELL = Path(__file__).resolve().parent / "modelle" / "ziffern.onnx"
if getattr(sys, "frozen", False):  # PyInstaller
    MODELL = Path(getattr(sys, "_MEIPASS")) / "labinett" / "modelle" / "ziffern.onnx"

MIN_SICHERHEIT = 0.90  # Softmax je Ziffer; synthetisch: 82 % richtig, 17 % offen, 1 % falsch
KEINE_ZIFFER = 10  # Klasse „keine einzelne Ziffer“ (Bruchstück, zwei Ziffern)
MAX_ZIFFERN = 3
MEHR_ZIFFERN_MALUS = 0.03  # je weitere Ziffer, beim Vergleich der Zerlegungen

# Normierung: Ziffer auf ARBEIT px Höhe/Breite, Strich auf STRICH px, dann auf 20 px
ARBEIT = 80
STRICH = 11.0  # entspricht ≈ 2,75 px bei 20 px – typische MNIST-Strichstärke


@dataclass
class Lesung:
    nummer: str | None
    ziffern: list[tuple[int, float]]  # (Ziffer, Sicherheit) je erkannter Ziffer
    grund: str = ""


# ---------------------------------------------------------------- Normierung


def strichstaerke(maske: np.ndarray) -> float:
    """Mittlere Strichstärke in px: 2 · Fläche / Umfang."""
    flaeche = float(np.count_nonzero(maske))
    if flaeche == 0:
        return 0.0
    konturen, _ = cv2.findContours(maske, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    umfang = sum(cv2.arcLength(k, True) for k in konturen)
    return 2 * flaeche / max(umfang, 1.0)


def normiere(maske: np.ndarray) -> np.ndarray:
    """Binäre Ziffernmaske (255 = Tinte) → 28 × 28 float32 im MNIST-Format (0..1)."""
    ys, xs = np.nonzero(maske)
    if len(xs) == 0:
        return np.zeros((28, 28), np.float32)
    z = maske[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    h, w = z.shape
    f = (ARBEIT - 2 * STRICH) / max(h, w)
    z = cv2.resize(z, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_LINEAR)
    z = cv2.copyMakeBorder(z, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=0)
    z = (z > 127).astype(np.uint8) * 255
    # Strichstärke angleichen
    s = strichstaerke(z)
    d = int(round((STRICH - s) / 2))
    if d != 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(d) + 1, 2 * abs(d) + 1))
        z2 = cv2.dilate(z, k) if d > 0 else cv2.erode(z, k)
        if np.count_nonzero(z2):
            z = z2
    ys, xs = np.nonzero(z)
    z = z[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    h, w = z.shape
    f = 20 / max(h, w)
    z = cv2.resize(z, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_AREA)
    z = z.astype(np.float32) / 255
    h, w = z.shape
    aus = np.zeros((28, 28), np.float32)
    m = z.sum()
    cy = (np.arange(h) @ z.sum(axis=1)) / m if m else h / 2
    cx = (np.arange(w) @ z.sum(axis=0)) / m if m else w / 2
    oy = int(np.clip(round(14 - cy), 0, 28 - h))
    ox = int(np.clip(round(14 - cx), 0, 28 - w))
    aus[oy : oy + h, ox : ox + w] = z
    return aus


# ---------------------------------------------------------------- Segmentierung


def _kreis(grau: np.ndarray, bh: np.ndarray) -> tuple[float, float, float]:
    """Gedruckter Kreis: Hough als Startwert, dann Kreisfit auf die dunklen Ringpixel."""
    H, W = grau.shape
    k = cv2.HoughCircles(
        cv2.medianBlur(grau, 5), cv2.HOUGH_GRADIENT, 1.2, 100,
        param1=80, param2=30, minRadius=int(W * 0.25), maxRadius=int(W * 0.56),
    )
    cx, cy, r = (W / 2, H / 2, W * 0.4) if k is None else (float(v) for v in k[0][0])
    ring = bh > max(10.0, float(np.percentile(bh, 90)))
    ys, xs = np.nonzero(ring)
    for band in (0.2, 0.1, 0.06):
        d = np.hypot(xs - cx, ys - cy)
        sel = np.abs(d - r) < band * r
        if sel.sum() < 30:
            break
        x, y = xs[sel].astype(float), ys[sel].astype(float)
        A = np.column_stack([x, y, np.ones_like(x)])
        a, b, c = np.linalg.lstsq(A, x**2 + y**2, rcond=None)[0]
        cx, cy = a / 2, b / 2
        r = float(np.sqrt(max(c + cx**2 + cy**2, 1.0)))
    return cx, cy, r


def tinte(ausschnitt_bgr: np.ndarray) -> np.ndarray:
    """Binärmaske der Handschrift im Kreisinneren (255 = Tinte)."""
    grau = cv2.cvtColor(ausschnitt_bgr, cv2.COLOR_BGR2GRAY)
    # dunkler als das Papier ringsum; Black-Hat entfernt Beleuchtungsverläufe
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    bh = cv2.morphologyEx(cv2.GaussianBlur(grau, (3, 3), 0), cv2.MORPH_BLACKHAT, k)
    cx, cy, r = _kreis(grau, bh)
    innen = np.zeros_like(grau)
    cv2.circle(innen, (round(cx), round(cy)), max(1, int(r * 0.88)), 255, -1)
    werte = bh[innen > 0].astype(np.float64)
    # Papierrauschen schätzen, Schwelle deutlich darüber
    med = float(np.median(werte))
    rauschen = med + 3 * 1.4826 * float(np.median(np.abs(werte - med)))
    schwelle = max(10.0, rauschen + 6)
    m = ((bh > schwelle) & (innen > 0)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # kleine Flecken und Reste des Kreisrings weg
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    min_flaeche = max(6, int(r * 0.15))
    min_ausdehnung = r * 0.22
    yy, xx = np.mgrid[0 : m.shape[0], 0 : m.shape[1]]
    radius = np.hypot(xx - cx, yy - cy)
    sauber = np.zeros_like(m)
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < min_flaeche or max(w, h) < min_ausdehnung:
            continue
        # Rest des gedruckten Rings: liegt außen und folgt dem Kreis (Radius fast konstant)
        rad = radius[lab == i]
        if rad.mean() > 0.78 * r and np.percentile(rad, 90) - np.percentile(rad, 10) < 0.07 * r:
            continue
        sauber[lab == i] = 255
    return sauber


def ziffern_masken(tinte_maske: np.ndarray) -> list[np.ndarray]:
    """Teilt die Tinte in Zeichengruppen (links → rechts).

    Eine Gruppe kann mehrere sich berührende Ziffern enthalten; die trennt
    ``lies_nummer`` erst mithilfe des Netzes (``_beste_zerlegung``).
    """
    n, lab, st, _ = cv2.connectedComponentsWithStats(tinte_maske, connectivity=8)
    if n <= 1:
        return []
    hoehe = int(max(st[i][3] for i in range(1, n)))
    # (x0, x1, y0, y1, ids)
    teile = [
        [int(st[i][0]), int(st[i][0] + st[i][2]), int(st[i][1]), int(st[i][1] + st[i][3]), [i]]
        for i in range(1, n)
    ]
    teile.sort()
    gruppen: list[list] = []
    for t in teile:
        if gruppen:
            g = gruppen[-1]
            ueberlapp = min(g[1], t[1]) - max(g[0], t[0])
            # Bruchstück (Querstrich der 5/7, Fähnchen) gehört zur Ziffer, mit der es
            # sich in x überlappt; zwei volle Ziffern (z. B. eine schmale 1) nicht
            kurz = min(g[3] - g[2], t[3] - t[2]) < 0.7 * hoehe
            if ueberlapp > 0.4 * min(t[1] - t[0], g[1] - g[0]) and (kurz or ueberlapp > 0.7 * min(t[1] - t[0], g[1] - g[0])):
                g[0], g[1] = min(g[0], t[0]), max(g[1], t[1])
                g[2], g[3] = min(g[2], t[2]), max(g[3], t[3])
                g[4] += t[4]
                continue
        gruppen.append(t)
    masken = []
    for *_, ids in gruppen:
        m = np.isin(lab, ids).astype(np.uint8) * 255
        ys, xs = np.nonzero(m)
        # Bruchstücke (Punkt, kurzer Strich) neben einer Ziffer ignorieren
        if ys.max() - ys.min() < 0.35 * hoehe:
            continue
        masken.append(m)
    return masken


def _schnitte(m: np.ndarray, hoehe: float, anzahl: int) -> list[list[np.ndarray]]:
    """Mögliche Zerlegungen einer Gruppe in ``anzahl`` Ziffern an dünnen Spalten."""
    ys, xs = np.nonzero(m)
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    if anzahl == 1:
        return [[m]]
    profil = np.convolve((m[:, x0:x1] > 0).sum(axis=0).astype(float), np.ones(3) / 3, mode="same")
    mindest = max(2, int(0.12 * hoehe))  # schmalste Ziffer (eine 1)
    kandidaten = [
        c for c in range(mindest, len(profil) - mindest)
        if profil[c] <= profil[c - 1] and profil[c] <= profil[c + 1]
    ]
    kandidaten = sorted(kandidaten, key=lambda c: profil[c])[:6]
    if anzahl == 2:
        kombis = [(c,) for c in kandidaten]
    else:
        kombis = [(a, b) for a in kandidaten for b in kandidaten if b - a >= mindest]
    zerlegungen = []
    for kombi in kombis:
        grenzen = [x0, *(x0 + c for c in kombi), x1]
        teile = []
        for a, b in zip(grenzen, grenzen[1:]):
            t = np.zeros_like(m)
            t[:, a:b] = m[:, a:b]
            if np.count_nonzero(t) < 4:
                break
            teile.append(t)
        else:
            zerlegungen.append(teile)
    return zerlegungen


def _zerlegungen(m: np.ndarray, hoehe: float, frei: int) -> list[np.ndarray]:
    """Mögliche Zerlegungen einer Gruppe in 1…3 Ziffern, je als Wahrscheinlichkeiten (k × 11).

    Breite Gruppen können keine einzelne Ziffer sein, schmale keine zwei.
    """
    ys, xs = np.nonzero(m)
    breite = xs.max() - xs.min() + 1
    h = ys.max() - ys.min() + 1
    moeglich = [k for k in (1, 2, 3) if k <= frei]
    if breite > 1.05 * h:
        moeglich = [k for k in moeglich if k >= 2] or moeglich
    if breite < 0.55 * h:
        moeglich = [1]
    if breite < 1.3 * h:
        moeglich = [k for k in moeglich if k <= 2]
    alle = [teile for k in moeglich for teile in _schnitte(m, hoehe, k)]

    def gleich_hoch(teile: list[np.ndarray]) -> bool:
        # Ziffern einer Nummer sind etwa gleich hoch; ein Teil deutlich kürzer als der
        # höchste ist ein Bruchstück (z. B. das Fähnchen einer 1), keine Ziffer
        hoehen = [float(np.ptp(np.nonzero(t)[0]) + 1) for t in teile]
        return min(hoehen) >= 0.72 * max(hoehen)

    passend = [t for t in alle if gleich_hoch(t)] or alle or [[m]]
    return [klassifiziere([normiere(t) for t in teile]) for teile in passend]


def _beste_nummer(
    varianten: list[np.ndarray], nummer_min: int, nummer_max: int
) -> tuple[str, list[float]] | None:
    """Wahrscheinlichste gültige Nummer über alle Zerlegungen.

    Bewertet wird die schlechteste Einzelsicherheit, bei Gleichstand das Produkt.
    Ungültige Nummern (führende 0, außerhalb des Bereichs) kommen nicht in Frage,
    so wird z. B. aus einer unsicheren „3“ vorne eher eine „2“.
    """
    beste, beste_wert = None, (-1.0, -1.0)
    for P in varianten:
        n = len(P)
        if not 1 <= n <= MAX_ZIFFERN:
            continue
        for zahl in range(max(nummer_min, 10 ** (n - 1) if n > 1 else 0), min(nummer_max, 10**n - 1) + 1):
            text = str(zahl)
            if len(text) != n:
                continue
            s = [float(P[i, int(c)]) for i, c in enumerate(text)]
            # bei ähnlicher Sicherheit die Lesart mit weniger Ziffern (eine 1 mit langem
            # Aufstrich ist sonst leicht „11“)
            wert = (min(s) - MEHR_ZIFFERN_MALUS * (n - 1), float(np.prod(s)))
            if wert > beste_wert:
                beste, beste_wert = (text, s), wert
    return beste


# ---------------------------------------------------------------- Netz


@lru_cache(maxsize=1)
def _netz() -> cv2.dnn.Net | None:
    if not MODELL.exists():
        return None
    return cv2.dnn.readNetFromONNX(str(MODELL))


def klassifiziere(bilder: list[np.ndarray]) -> np.ndarray:
    """28 × 28-Bilder → Wahrscheinlichkeiten (N × 11, Spalte 10 = keine Ziffer)."""
    netz = _netz()
    n = KEINE_ZIFFER + 1
    if netz is None or not bilder:
        return np.zeros((len(bilder), n), np.float32)
    logits = np.zeros((len(bilder), n), np.float32)
    for i, b in enumerate(bilder):  # Modell mit fester Batchgröße 1
        netz.setInput(b[None, None].astype(np.float32))
        logits[i] = netz.forward().reshape(n)
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def lies_nummer(
    ausschnitt_bgr: np.ndarray, nummer_min: int = 1, nummer_max: int = 250
) -> Lesung:
    if _netz() is None:
        return Lesung(None, [], "Ziffernmodell fehlt")
    gruppen = ziffern_masken(tinte(ausschnitt_bgr))
    if not gruppen:
        return Lesung(None, [], "keine Nummer im Kreis")
    if len(gruppen) > MAX_ZIFFERN:
        return Lesung(None, [], f"{len(gruppen)} Zeichen im Kreis")
    hoehe = max(float(np.ptp(np.nonzero(g)[0]) + 1) for g in gruppen)
    # Zerlegungen aller Gruppen kombinieren (höchstens 3 Ziffern insgesamt)
    varianten: list[np.ndarray] = [np.zeros((0, KEINE_ZIFFER + 1), np.float32)]
    for i, g in enumerate(gruppen):
        rest = len(gruppen) - i - 1
        neu = []
        for v in varianten:
            frei = MAX_ZIFFERN - len(v) - rest
            if frei < 1:
                continue
            neu += [np.vstack([v, z]) for z in _zerlegungen(g, hoehe, frei)]
        varianten = neu
    erg = _beste_nummer(varianten, nummer_min, nummer_max)
    if erg is None:
        return Lesung(None, [], f"keine gültige Nummer {nummer_min}–{nummer_max}")
    text, sicher = erg
    ziffern = [(int(c), s) for c, s in zip(text, sicher)]
    if min(sicher) < MIN_SICHERHEIT:
        return Lesung(None, ziffern, f"unsicher gelesen: {text}?")
    return Lesung(text, ziffern)


def abstimmen(lesungen: list[Lesung]) -> Lesung:
    """Mehrere Aufnahmen derselben Karte: Nummer nur, wenn die Mehrheit sicher dasselbe liest
    und keine Aufnahme sicher etwas anderes."""
    if not lesungen:
        return Lesung(None, [], "kein Bild")
    sicher = [l for l in lesungen if l.nummer]
    nummern = sorted({l.nummer for l in sicher})
    if len(nummern) > 1:
        return Lesung(None, sicher[0].ziffern, "Aufnahmen uneinig: " + " / ".join(nummern))
    if sicher and 2 * len(sicher) > len(lesungen):
        return sicher[0]
    if sicher:
        return Lesung(None, sicher[0].ziffern, f"nur {len(sicher)} von {len(lesungen)} Aufnahmen sicher: {nummern[0]}?")
    return next((l for l in lesungen if l.ziffern), lesungen[0])
