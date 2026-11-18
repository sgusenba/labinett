"""CSV-Ausgabe: eine Zeile pro Karte, nur anhängen.

UTF-8 mit BOM und ';' als Trennzeichen, damit Excel auf deutschem Windows
die Datei ohne Import-Dialog richtig öffnet.

Ist die Datei gesperrt (z. B. in Excel geöffnet) oder das Ziel nicht erreichbar
(USB-Stick abgezogen, Netzlaufwerk weg), landen Zeilen in einer Warteschlange
(JSON-Lines) und werden beim nächsten Versuch in der richtigen Reihenfolge
nachgetragen. Es geht nichts verloren.
"""

from __future__ import annotations

import csv
import json
import os
import uuid
from pathlib import Path

from .karte import SCHUESSE_PRO_KARTE, Karte

SPALTEN = (
    ["zeitstempel", "karten_uuid", "schuetzennummer", "nummer_quelle"]
    + [f"s{n}_{teil}" for n in range(1, SCHUESSE_PRO_KARTE + 1) for teil in ("felder", "wert")]
    + ["gesamt", "status", "bemerkung"]
)

TRENNER = ";"
ENCODING = "utf-8-sig"


class FremdeDatei(ValueError):
    """Die Datei existiert, hat aber nicht die Spalten von labinett."""


def karte_als_zeile(karte: Karte) -> dict[str, str]:
    zeile = {
        "zeitstempel": karte.zeitstempel.isoformat(),
        "karten_uuid": karte.karten_uuid or "",
        "schuetzennummer": karte.schuetzennummer or "",
        "nummer_quelle": karte.nummer_quelle,
        "gesamt": str(karte.gesamt),
        "status": karte.status,
        "bemerkung": "; ".join(filter(None, [karte.bemerkung, *karte.gruende_pruefen])),
    }
    for n in range(1, SCHUESSE_PRO_KARTE + 1):
        if n <= len(karte.schuesse):
            s = karte.schuesse[n - 1]
            zeile[f"s{n}_felder"] = "+".join(str(f) for f in s.felder)
            zeile[f"s{n}_wert"] = str(s.wert)
        else:
            zeile[f"s{n}_felder"] = ""
            zeile[f"s{n}_wert"] = ""
    return zeile


def _kopf_passt(pfad: Path) -> bool:
    with pfad.open(newline="", encoding=ENCODING) as f:
        kopf = next(csv.reader(f, delimiter=TRENNER), None)
    return kopf == SPALTEN


def pruefe_ziel(pfad: str | Path) -> None:
    """Prüft, ob in ``pfad`` geschrieben werden kann, ohne fremde Daten zu gefährden.

    Wirft ``FremdeDatei`` bei einer vorhandenen Datei mit anderen Spalten und
    ``OSError``, wenn der Ordner nicht beschreibbar ist.
    """
    pfad = Path(pfad)
    if pfad.is_dir():
        raise FremdeDatei(f"{pfad} ist ein Ordner, bitte einen Dateinamen angeben")
    if pfad.exists() and pfad.stat().st_size > 0 and not _kopf_passt(pfad):
        raise FremdeDatei(f"{pfad} gehört nicht zu labinett (andere Spalten) und wird nicht verändert")
    pfad.parent.mkdir(parents=True, exist_ok=True)
    probe = pfad.parent / f".labinett-probe-{uuid.uuid4().hex[:8]}"
    probe.write_text("", encoding="utf-8")
    probe.unlink()


def _schreibe_zeilen(pfad: Path, zeilen: list[dict[str, str]]) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    neu = not pfad.exists() or pfad.stat().st_size == 0
    if not neu and not _kopf_passt(pfad):
        raise FremdeDatei(f"{pfad} gehört nicht zu labinett (andere Spalten) und wird nicht verändert")
    # BOM nur beim Anlegen schreiben
    with pfad.open("a", newline="", encoding=ENCODING if neu else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=TRENNER)
        if neu:
            w.writeheader()
        w.writerows(zeilen)
        f.flush()
        os.fsync(f.fileno())


def anhaengen(pfad: str | Path, karte: Karte) -> None:
    """Hängt eine Karte an die CSV an; legt Datei und Kopfzeile bei Bedarf an."""
    _schreibe_zeilen(Path(pfad), [karte_als_zeile(karte)])


def _lade_warteschlange(ws: Path) -> list[dict[str, str]]:
    if not ws.exists():
        return []
    return [json.loads(z) for z in ws.read_text(encoding="utf-8").splitlines() if z.strip()]


def _schreibe_warteschlange(ws: Path, zeilen: list[dict[str, str]]) -> None:
    ws.parent.mkdir(parents=True, exist_ok=True)
    tmp = ws.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(z, ensure_ascii=False) + "\n" for z in zeilen), encoding="utf-8")
    tmp.replace(ws)


def ausstehend(ws: str | Path) -> int:
    return len(_lade_warteschlange(Path(ws)))


def speichern(pfad: str | Path, karte: Karte, ws: str | Path) -> bool:
    """Schreibt erst ausstehende Zeilen, dann die Karte.

    Gibt ``True`` zurück, wenn alles in der CSV steht, ``False``, wenn die Zeilen
    in der Warteschlange warten (Datei gesperrt oder Ziel nicht erreichbar).
    ``FremdeDatei`` wird durchgereicht – dann wird nichts geschrieben.
    """
    pfad, ws = Path(pfad), Path(ws)
    zeilen = _lade_warteschlange(ws) + [karte_als_zeile(karte)]
    try:
        _schreibe_zeilen(pfad, zeilen)
    except FremdeDatei:
        raise
    except OSError:
        _schreibe_warteschlange(ws, zeilen)
        return False
    ws.unlink(missing_ok=True)
    return True


def nachtragen(pfad: str | Path, ws: str | Path) -> int:
    """Versucht ausstehende Zeilen zu schreiben; gibt die Zahl der noch offenen zurück."""
    pfad, ws = Path(pfad), Path(ws)
    zeilen = _lade_warteschlange(ws)
    if not zeilen:
        return 0
    try:
        _schreibe_zeilen(pfad, zeilen)
    except OSError:  # FremdeDatei ist ValueError und bleibt sichtbar
        return len(zeilen)
    ws.unlink(missing_ok=True)
    return 0


def lesen(pfad: str | Path) -> list[dict[str, str]]:
    with Path(pfad).open(newline="", encoding=ENCODING) as f:
        return list(csv.DictReader(f, delimiter=TRENNER))
