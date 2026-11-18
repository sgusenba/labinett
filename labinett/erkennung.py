"""Bilderkennung: Raute finden, entzerren, Einschusslöcher finden.

Annahmen
- Karte liegt aufrecht: Feld 23 ist die oberste Spitze der Raute im Bild.
  (``drehung`` erlaubt 90°-Schritte, falls die Kamera anders montiert ist.)
- Unterlage ist dunkel, damit die Löcher als dunkle Flecken erscheinen.

Ablauf
1. Gitter als zusammenhängende dunkle Linienstruktur mit ~25 Innenflächen finden.
2. Vier Spitzen der Raute bestimmen, Homographie auf ein Normbild rechnen
   (``PX`` Pixel pro Feld, ``RAND`` Feldbreiten Rand rundum).
3. Gitterlinien im Normbild per Projektionsprofil nachjustieren.
4. Linien und Ziffern per morphologischem Öffnen entfernen, übrig bleiben Löcher.
5. Überlappende Löcher anhand der Fläche aufteilen (k-Means), Ziel: 5 Schüsse.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .karte import SCHUESSE_PRO_KARTE
from .scheibe import Geometrie

PX = 100  # Pixel pro Feld im Normbild
RAND = 0.6  # Rand ums Raster im Normbild, in Feldbreiten
NORM = int(round((5 + 2 * RAND) * PX))


class ErkennungsFehler(Exception):
    pass


@dataclass
class Erkennung:
    ecken_bild: np.ndarray  # 4x2: oben(23), rechts(25), unten(22), links(24)
    positionen: list[tuple[float, float]]  # Lochmittelpunkte in Rasterkoordinaten
    loch_flaeche_rel: float  # gemessene / erwartete Fläche aller Löcher
    hinweise: list[str] = field(default_factory=list)
    normbild: np.ndarray | None = None


# ---------------------------------------------------------------- Gitter


def _binaer(grau: np.ndarray) -> np.ndarray:
    k = max(15, (min(grau.shape) // 40) | 1)
    return cv2.adaptiveThreshold(
        grau, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, k, 15
    )


def _finde_gitter_maske(grau: np.ndarray) -> np.ndarray:
    """Komponente mit den meisten zellgroßen Innenflächen = Raster."""
    th = _binaer(grau)
    n, lab, st, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    H, W = grau.shape
    beste, beste_zellen = None, 0
    reihenfolge = np.argsort(-(st[:, 2] * st[:, 3]))
    for idx in reihenfolge[:12]:
        if idx == 0:
            continue
        x, y, w, h, a = st[idx]
        if w < W * 0.15 or h < H * 0.1:
            continue
        maske = (lab[y : y + h, x : x + w] == idx).astype(np.uint8) * 255
        kont, hier = cv2.findContours(maske, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hier is None:
            continue
        zell_min = (w * h) / 25 * 0.25
        zell_max = (w * h) / 25 * 1.2
        zellen = sum(
            1
            for k, hh in zip(kont, hier[0])
            if hh[3] >= 0 and zell_min < cv2.contourArea(k) < zell_max
        )
        if zellen > beste_zellen:
            beste_zellen = zellen
            voll = np.zeros_like(th)
            voll[lab == idx] = 255
            beste = voll
    if beste is None or beste_zellen < 12:
        raise ErkennungsFehler("Kein Raster gefunden – liegt die Karte vollständig im Bild?")
    return beste


def _ecken(maske: np.ndarray, drehung: int) -> np.ndarray:
    """Vier Rautenspitzen: oben, rechts, unten, links (im Uhrzeigersinn ab Feld 23)."""
    pts = cv2.findNonZero(maske).reshape(-1, 2).astype(np.float64)
    x, y = pts[:, 0], pts[:, 1]
    # Extrempunkte entlang der Achsen; robust gegen Löcher an Spitzen über Quantile
    def extrem(werte: np.ndarray, maximal: bool) -> np.ndarray:
        q = np.quantile(werte, 0.9995 if maximal else 0.0005)
        sel = pts[werte >= q] if maximal else pts[werte <= q]
        return sel.mean(axis=0)

    oben, unten = extrem(y, False), extrem(y, True)
    links, rechts = extrem(x, False), extrem(x, True)
    grob = np.array([oben, rechts, unten, links])
    ecken = _verfeinere_ecken(pts, grob)
    return np.roll(ecken, -(drehung % 4), axis=0)


def _verfeinere_ecken(pts: np.ndarray, grob: np.ndarray) -> np.ndarray:
    """Außenkanten als Geraden fitten (mittlere 70 % jeder Kante) und schneiden.

    Löcher an den Spitzen verfälschen so die Ecken nicht.
    """
    geraden = []
    for k in range(4):
        a, b = grob[k], grob[(k + 1) % 4]
        d = b - a
        laenge = float(np.linalg.norm(d))
        if laenge < 1:
            return grob
        e = d / laenge
        n = np.array([-e[1], e[0]])
        rel = pts - a
        t = rel @ e
        s = rel @ n
        band = laenge * 0.04
        sel = pts[(t > 0.15 * laenge) & (t < 0.85 * laenge) & (np.abs(s) < band)]
        if len(sel) < 20:
            return grob
        # nur die äußerste Linie: Punkte auf der Außenseite (vom Mittelpunkt weg)
        mitte = grob.mean(axis=0)
        aussen_richtung = np.sign((a - mitte) @ n) or 1.0
        s_sel = (sel - a) @ n * aussen_richtung
        grenze = np.quantile(s_sel, 0.3)
        sel = sel[s_sel >= grenze]
        vx, vy, x0, y0 = cv2.fitLine(sel.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        geraden.append((np.array([x0, y0], dtype=np.float64), np.array([vx, vy], dtype=np.float64)))
    ecken = []
    for k in range(4):
        p1, r1 = geraden[(k - 1) % 4]
        p2, r2 = geraden[k]
        A = np.column_stack([r1, -r2])
        if abs(np.linalg.det(A)) < 1e-6:
            return grob
        t = np.linalg.solve(A, p2 - p1)
        ecken.append(p1 + t[0] * r1)
    return np.array(ecken)


def _homographie(ecken: np.ndarray) -> np.ndarray:
    r = RAND * PX
    ziel = np.array(
        [[r, r], [r + 5 * PX, r], [r + 5 * PX, r + 5 * PX], [r, r + 5 * PX]], dtype=np.float64
    )
    # oben(23)=(0,0), rechts(25)=(5,0), unten(22)=(5,5), links(24)=(0,5) in (u,v)
    return cv2.getPerspectiveTransform(ecken.astype(np.float32), ziel.astype(np.float32))


def _justiere(norm_bin: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Linienlagen (6 je Achse) per Projektionsprofil, liefert Pixelpositionen."""
    innen = norm_bin.copy()
    # nur dünne Strukturen (Linien) betrachten
    ergebnisse = []
    for achse in (0, 1):  # 0: Spalten -> u-Linien, 1: Zeilen -> v-Linien
        profil = innen.sum(axis=achse).astype(np.float64)
        lagen = []
        for k in range(6):
            soll = RAND * PX + k * PX
            a, b = int(soll - 0.15 * PX), int(soll + 0.15 * PX)
            a, b = max(a, 0), min(b, len(profil))
            fenster = profil[a:b]
            lagen.append(a + float(np.argmax(fenster)) if fenster.max() > 0 else soll)
        ergebnisse.append(np.array(lagen))
    return ergebnisse[0], ergebnisse[1]


def _pixel_zu_raster(p: float, lagen: np.ndarray) -> float:
    """Stückweise lineare Abbildung Normbild-Pixel -> Rasterkoordinate."""
    idx = np.arange(6, dtype=np.float64)
    if p <= lagen[0]:
        return (p - lagen[0]) / (lagen[1] - lagen[0])
    if p >= lagen[-1]:
        return 5 + (p - lagen[-1]) / (lagen[-1] - lagen[-2])
    return float(np.interp(p, lagen, idx))


# ---------------------------------------------------------------- Löcher


def _loch_maske(norm_grau: np.ndarray, loch_r_px: float) -> np.ndarray:
    # Löcher sind deutlich dunkler als Druckerschwärze auf Papier? Nicht immer –
    # daher: dunkel UND kompakt (überlebt Öffnen mit Scheibe > Linien-/Ziffernstärke).
    _, dunkel = cv2.threshold(norm_grau, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    d = max(5, int(loch_r_px * 1.1)) | 1
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
    offen = cv2.morphologyEx(dunkel, cv2.MORPH_OPEN, kern)
    return offen


def _teile_flecken(
    maske: np.ndarray, einzel_flaeche: float, soll: int
) -> tuple[list[tuple[float, float]], float]:
    n, lab, st, cen = cv2.connectedComponentsWithStats(maske)
    H, W = maske.shape
    flecken = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < einzel_flaeche * 0.35:
            continue
        # Flecken am Bildrand sind Unterlage neben einer angeschnittenen Karte
        if x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:
            continue
        flecken.append((i, a))
    if not flecken:
        return [], 0.0
    gesamt = sum(a for _, a in flecken)
    # Anzahl je Fleck: mindestens 1, Rest nach Flächenüberschuss verteilen
    anz = {i: max(1, int(round(a / einzel_flaeche))) for i, a in flecken}
    while sum(anz.values()) < soll:
        # Fleck mit dem größten Flächenüberschuss pro angenommenem Loch
        i = max(flecken, key=lambda f: f[1] / anz[f[0]])[0]
        if dict(flecken)[i] / (anz[i] + 1) < einzel_flaeche * 0.4:
            break
        anz[i] += 1
    while sum(anz.values()) > soll:
        kandidaten = [f for f in flecken if anz[f[0]] > 1]
        if not kandidaten:
            break
        i = min(kandidaten, key=lambda f: f[1] / anz[f[0]])[0]
        anz[i] -= 1
    punkte: list[tuple[float, float]] = []
    for i, _ in flecken:
        k = anz[i]
        if k == 1:
            punkte.append((float(cen[i][0]), float(cen[i][1])))
            continue
        ys, xs = np.nonzero(lab == i)
        daten = np.column_stack([xs, ys]).astype(np.float32)
        krit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.2)
        _, _, zentren = cv2.kmeans(daten, k, None, krit, 5, cv2.KMEANS_PP_CENTERS)
        punkte.extend((float(c[0]), float(c[1])) for c in zentren)
    return punkte, gesamt / (einzel_flaeche * max(1, len(punkte)))


# ---------------------------------------------------------------- Einstieg


def erkenne(bild_bgr: np.ndarray, geo: Geometrie, drehung: int = 0) -> Erkennung:
    grau = cv2.cvtColor(bild_bgr, cv2.COLOR_BGR2GRAY)
    maske = _finde_gitter_maske(grau)
    ecken = _ecken(maske, drehung)
    Hm = _homographie(ecken)
    norm = cv2.warpPerspective(grau, Hm, (NORM, NORM), flags=cv2.INTER_LINEAR, borderValue=0)
    norm_gitter = cv2.warpPerspective(maske, Hm, (NORM, NORM), flags=cv2.INTER_NEAREST)
    u_lagen, v_lagen = _justiere(norm_gitter)

    loch_r_px = geo.lochdurchmesser_mm / 2 / geo.feldgroesse_mm * PX
    einzel = np.pi * loch_r_px**2
    lmaske = _loch_maske(norm, loch_r_px)
    pix, rel = _teile_flecken(lmaske, einzel, SCHUESSE_PRO_KARTE)

    positionen = [
        (_pixel_zu_raster(px, u_lagen), _pixel_zu_raster(py, v_lagen)) for px, py in pix
    ]
    # Lochpositionen außerhalb der Normbild-Ränder (Kartenrand/Unterlage) verwerfen
    positionen = [(u, v) for u, v in positionen if -RAND * 0.8 < u < 5 + RAND * 0.8 and -RAND * 0.8 < v < 5 + RAND * 0.8]
    if len(positionen) > SCHUESSE_PRO_KARTE:
        # zuerst Kandidaten weit außerhalb des Rasters verwerfen
        def aussen(p: tuple[float, float]) -> float:
            u, v = p
            return max(-u, u - 5, -v, v - 5, 0.0)

        positionen.sort(key=aussen)
        while len(positionen) > SCHUESSE_PRO_KARTE and aussen(positionen[-1]) > 0.25:
            positionen.pop()
    positionen.sort(key=lambda p: (p[0] + p[1], p[0] - p[1]))

    hinweise = []
    if len(positionen) != SCHUESSE_PRO_KARTE:
        hinweise.append(f"{len(positionen)} Löcher erkannt")
    return Erkennung(
        ecken_bild=ecken, positionen=positionen, loch_flaeche_rel=rel, hinweise=hinweise, normbild=norm
    )


def ecken_stabil(a: np.ndarray | None, b: np.ndarray | None, toleranz_px: float = 6.0) -> bool:
    if a is None or b is None:
        return False
    return float(np.max(np.linalg.norm(a - b, axis=1))) <= toleranz_px


def schnell_ecken(bild_bgr: np.ndarray, drehung: int = 0, max_breite: int = 640) -> np.ndarray | None:
    """Für die Live-Vorschau: Rautenspitzen auf verkleinertem Bild, None wenn keine Karte."""
    h, w = bild_bgr.shape[:2]
    f = min(1.0, max_breite / w)
    klein = cv2.resize(bild_bgr, None, fx=f, fy=f) if f < 1 else bild_bgr
    try:
        m = _finde_gitter_maske(cv2.cvtColor(klein, cv2.COLOR_BGR2GRAY))
    except ErkennungsFehler:
        return None
    return _ecken(m, drehung) / f


# ---------------------------------------------------------------- Schützennummer

# Lage des handschriftlichen Nummernkreises links oben, in Rasterkoordinaten
NUMMER_MITTE = (-2.55, 2.3)
NUMMER_HALB = 1.15  # halbe Ausschnittbreite in Feldbreiten
NUMMER_PX = 160


def nummern_ausschnitt(bild_bgr: np.ndarray, ecken: np.ndarray) -> np.ndarray:
    """Aufrecht gedrehter Bildausschnitt mit dem Kreis der Schützennummer."""
    Hm = _homographie(ecken)
    cu, cv = NUMMER_MITTE
    s = NUMMER_PX / (2 * NUMMER_HALB)
    w = 1 / np.sqrt(2)

    def ziel(u: float, v: float) -> tuple[float, float]:
        du, dv = u - cu, v - cv
        return ((du - dv) * w * s + NUMMER_PX / 2, (du + dv) * w * s + NUMMER_PX / 2)

    quelle_r = [(cu - 1, cv), (cu + 1, cv), (cu, cv + 1), (cu, cv - 1)]
    quelle = np.float32([[RAND * PX + u * PX, RAND * PX + v * PX] for u, v in quelle_r])
    ziel_px = np.float32([ziel(u, v) for u, v in quelle_r])
    A = cv2.getPerspectiveTransform(quelle, ziel_px)
    return cv2.warpPerspective(bild_bgr, A @ Hm, (NUMMER_PX, NUMMER_PX), borderValue=(40, 40, 40))


def erkenne_nummer(ausschnitt_bgr: np.ndarray) -> str | None:
    """Platzhalter: handschriftliche Ziffern werden (noch) nicht gelesen.

    Ein einfacher Ziffern-Klassifikator war auf den Testkarten unzuverlässig.
    Bis QR-Codes kommen, wird die Nummer in der Oberfläche eingegeben.
    """
    return None
