"""Ziffernmodell für die Schützennummer trainieren → labinett/modelle/ziffern.onnx

Nur für Entwickler, die App braucht kein Torch (Ausführung über OpenCV-DNN).

    pip install torch onnx
    curl -o mnist.npz https://storage.googleapis.com/tensorflow/tf-keras-datasets/mnist.npz
    python tools/ziffern_trainieren.py mnist.npz

Trainingsdaten: MNIST, so verfremdet, dass es wie die Kamera-Ausschnitte aussieht
(Drehung, Scherung, Breite, Strichstärke, Ziffernhöhe 22–60 px, neu binarisiert),
danach exakt dieselbe Normierung wie in der App (``labinett.nummer.normiere``).

Klasse 10 = „keine einzelne Ziffer“: zwei sich berührende Ziffern, halbe Ziffern,
Ziffer mit angeschnittenem Nachbarn. Damit kann ``lies_nummer`` falsche
Zerlegungen zusammenhängender Ziffern erkennen und verwerfen.
"""

from __future__ import annotations

import argparse
import sys
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from labinett.nummer import KEINE_ZIFFER, MODELL, normiere  # noqa: E402


def _gross(bild: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """MNIST-Ziffer vergrößert, verzerrt, Strich verändert; binär, auf Inhalt zugeschnitten."""
    m = cv2.resize(bild, (112, 112), interpolation=cv2.INTER_LINEAR)
    m = cv2.copyMakeBorder(m, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=0)
    c = m.shape[0] / 2
    winkel = np.deg2rad(rng.uniform(-18, 18))
    scher = rng.uniform(-0.4, 0.4)
    sx, sy = rng.uniform(0.7, 1.15), rng.uniform(0.9, 1.1)
    R = np.array([[np.cos(winkel), -np.sin(winkel)], [np.sin(winkel), np.cos(winkel)]])
    A = R @ np.array([[1, scher], [0, 1]]) @ np.diag([sx, sy])
    M = np.hstack([A, (np.array([c, c]) - A @ np.array([c, c]))[:, None]])
    m = cv2.warpAffine(m, M, m.shape[::-1], flags=cv2.INTER_LINEAR)
    d = int(rng.integers(-1, 4))
    if d:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(d) + 1,) * 2)
        m2 = cv2.dilate(m, k) if d > 0 else cv2.erode(m, k)
        if (m2 > 127).sum() > 30:
            m = m2
    m = (m > 127).astype(np.uint8) * 255
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return np.zeros((10, 10), np.uint8)
    return m[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def _klein(m: np.ndarray, rng: np.random.Generator, hoehe: int | None = None) -> np.ndarray:
    """Auf Kamera-Auflösung verkleinern und wieder binarisieren."""
    hoehe = hoehe or int(rng.integers(22, 61))
    f = hoehe / m.shape[0]
    groesse = (max(2, round(m.shape[1] * f)), max(2, round(m.shape[0] * f)))
    weich = cv2.resize(m, groesse, interpolation=cv2.INTER_AREA)
    k = (weich > rng.uniform(60, 140)).astype(np.uint8) * 255
    return k if k.any() else (weich > 0).astype(np.uint8) * 255


def _nebeneinander(a: np.ndarray, b: np.ndarray, luecke: int) -> np.ndarray:
    h = max(a.shape[0], b.shape[0])
    def hoch(x: np.ndarray) -> np.ndarray:
        oben = (h - x.shape[0]) // 2
        return cv2.copyMakeBorder(x, oben, h - x.shape[0] - oben, 0, 0, cv2.BORDER_CONSTANT, value=0)
    a, b = hoch(a), hoch(b)
    x = max(a.shape[1] // 3, a.shape[1] + luecke)  # höchstens zwei Drittel Überlappung
    aus = np.zeros((h, max(a.shape[1], x + b.shape[1])), np.uint8)
    aus[:, : a.shape[1]] = a
    aus[:, x : x + b.shape[1]] = np.maximum(aus[:, x : x + b.shape[1]], b)
    return aus


def eins_europaeisch(seed: int) -> np.ndarray:
    """Synthetische „1“ mit langem Aufstrich, wie sie auf den Karten steht (in MNIST selten)."""
    rng = np.random.default_rng(seed)
    H = 200
    m = np.zeros((H + 80, H + 80), np.uint8)
    o = 40
    xt = o + H * 0.5
    neig = np.deg2rad(rng.uniform(-10, 14))
    unten = (xt + H * np.tan(neig), o + H)
    a = np.deg2rad(rng.uniform(20, 55))  # Aufstrich gegen die Senkrechte (flacher wäre eine 7)
    # bis ganz nach unten (Λ-Form) nur bei steilem Aufstrich
    laenge = H * rng.uniform(0.25, 1.0 if a < np.deg2rad(35) else 0.75 if a < np.deg2rad(42) else 0.55)
    start = (xt - laenge * np.sin(a), o + laenge * np.cos(a))
    knick = (xt + rng.uniform(-4, 4), o + rng.uniform(-3, 6))
    bogen = rng.uniform(-0.08, 0.08) * H
    mitte = ((knick[0] + unten[0]) / 2 + bogen, (knick[1] + unten[1]) / 2)
    pts = np.array([start, knick, mitte, unten], np.float64)
    if rng.random() < 0.12:  # Fußstrich
        fuss = H * rng.uniform(0.15, 0.3)
        pts = np.vstack([pts, [unten[0] - fuss, unten[1]], [unten[0] + fuss, unten[1]]])
    dicke = int(rng.integers(5, 18))
    cv2.polylines(m, [np.round(pts[:4]).astype(np.int32)], False, 255, dicke, cv2.LINE_AA)
    if len(pts) > 4:
        cv2.line(m, tuple(np.round(pts[4]).astype(int)), tuple(np.round(pts[5]).astype(int)), 255, dicke, cv2.LINE_AA)
    m = (m > 127).astype(np.uint8) * 255
    ys, xs = np.nonzero(m)
    return normiere(_klein(m[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1], rng))


def ziffer(args: tuple[np.ndarray, int]) -> np.ndarray:
    bild, seed = args
    rng = np.random.default_rng(seed)
    return normiere(_klein(_gross(bild, rng), rng))


def keine_ziffer(args: tuple[np.ndarray, np.ndarray, bool, bool, int]) -> np.ndarray:
    a, b, a_ist_eins, b_ist_eins, seed = args
    rng = np.random.default_rng(seed)
    ga, gb = _gross(a, rng), _gross(b, rng)
    art = int(rng.integers(0, 3))
    if art == 0 or (art == 1 and a_ist_eins):
        # zwei Ziffern, die sich berühren oder überlappen
        # zwei überlappende 1en sähen aus wie eine 1 mit Aufstrich – nur mit Abstand
        m = _nebeneinander(ga, gb, int(rng.integers(0, 6)) if a_ist_eins and b_ist_eins else int(rng.integers(-25, 6)))
    elif art == 1:
        # Teil einer Ziffer (nie von einer 1 – die ist schmal und bleibt eine 1)
        w = ga.shape[1]
        anteil = rng.uniform(0.3, 0.62)
        m = ga[:, : max(2, int(w * anteil))] if rng.random() < 0.5 else ga[:, int(w * (1 - anteil)) :]
        ys, xs = np.nonzero(m)
        # schmale Reste (ein senkrechter Strich) sehen wie eine 1 aus – nicht als Negativ
        if len(xs) == 0 or (xs.max() - xs.min() + 1) < 0.45 * (ys.max() - ys.min() + 1):
            m = _nebeneinander(ga, gb, int(rng.integers(0, 6)))
    else:
        # Ziffer mit angeschnittenem Nachbarn
        w = gb.shape[1]
        stueck = gb[:, : max(2, int(w * rng.uniform(0.2, 0.45)))]
        m = _nebeneinander(ga, stueck, int(rng.integers(-10, 3))) if rng.random() < 0.5 else _nebeneinander(
            gb[:, int(w * rng.uniform(0.55, 0.8)) :], ga, int(rng.integers(-10, 3))
        )
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return np.zeros((28, 28), np.float32)
    m = m[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    return normiere(_klein(m, rng))


def _init() -> None:
    cv2.setNumThreads(1)


def datensatz(
    x: np.ndarray, y: np.ndarray, kopien: int, negativ: int, einsen: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    auf = [(x[i], seed * 10_000_000 + k * 100_000 + i) for k in range(kopien) for i in range(len(x))]
    ia, ib = rng.integers(0, len(x), negativ), rng.integers(0, len(x), negativ)
    neg = [
        (x[a], x[b], bool(y[a] == 1), bool(y[b] == 1), seed * 10_000_000 + 9_000_000 + i)
        for i, (a, b) in enumerate(zip(ia, ib))
    ]
    with Pool(initializer=_init) as pool:
        pos = pool.map(ziffer, auf, chunksize=500)
        negb = pool.map(keine_ziffer, neg, chunksize=500)
        eins = pool.map(eins_europaeisch, [seed * 10_000_000 + 8_000_000 + i for i in range(einsen)], chunksize=500)
    X = np.stack(pos + negb + eins)[:, None]
    Y = np.concatenate([np.tile(y, kopien), np.full(negativ, KEINE_ZIFFER), np.full(einsen, 1)]).astype(np.int64)
    return X, Y


def main() -> None:
    import torch
    import torch.nn as nn

    ap = argparse.ArgumentParser()
    ap.add_argument("mnist", type=Path)
    ap.add_argument("--kopien", type=int, default=3)
    ap.add_argument("--negativ", type=int, default=50_000)
    ap.add_argument("--einsen", type=int, default=15_000, help="synthetische 1 mit Aufstrich")
    ap.add_argument("--epochen", type=int, default=8)
    ap.add_argument("--ziel", type=Path, default=MODELL)
    a = ap.parse_args()

    d = dict(np.load(a.mnist, allow_pickle=False))
    print("verfremde Trainingsdaten …", flush=True)
    xt, yt = datensatz(d["x_train"], d["y_train"], a.kopien, a.negativ, a.einsen, 1)
    xv, yv = datensatz(d["x_test"], d["y_test"], 1, 5_000, 0, 2)

    torch.manual_seed(0)
    netz = nn.Sequential(
        nn.Conv2d(1, 32, 3, padding=1), nn.ReLU(),
        nn.Conv2d(32, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(),
        nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
        nn.Flatten(), nn.Dropout(0.3), nn.Linear(64 * 7 * 7, 64), nn.ReLU(), nn.Linear(64, KEINE_ZIFFER + 1),
    )
    opt = torch.optim.AdamW(netz.parameters(), lr=2e-3, weight_decay=1e-4)
    Xt, Yt = torch.from_numpy(xt), torch.from_numpy(yt)
    Xv, Yv = torch.from_numpy(xv), torch.from_numpy(yv)
    schritte = a.epochen * ((len(Xt) + 255) // 256)
    plan = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-3, total_steps=schritte)
    for ep in range(a.epochen):
        netz.train()
        perm = torch.randperm(len(Xt))
        for i in range(0, len(Xt), 256):
            idx = perm[i : i + 256]
            verlust = nn.functional.cross_entropy(netz(Xt[idx]), Yt[idx])
            opt.zero_grad()
            verlust.backward()
            opt.step()
            plan.step()
        netz.eval()
        with torch.no_grad():
            vorh = torch.cat([netz(Xv[i : i + 2000]).argmax(1) for i in range(0, len(Xv), 2000)])
        z = Yv < KEINE_ZIFFER
        print(
            f"Epoche {ep + 1}: Verlust {verlust.item():.3f}, Ziffern {(vorh[z] == Yv[z]).float().mean():.4f}, "
            f"„keine Ziffer“ erkannt {(vorh[~z] == KEINE_ZIFFER).float().mean():.4f}",
            flush=True,
        )

    a.ziel.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        netz, torch.zeros(1, 1, 28, 28), str(a.ziel), input_names=["bild"], output_names=["logits"],
        opset_version=13, dynamo=False,
    )
    print("gespeichert:", a.ziel)


if __name__ == "__main__":
    main()
