"""CSV-Ausgabe: eine Zeile pro Karte, nur anhängen.

UTF-8 mit BOM und ';' als Trennzeichen, damit Excel auf deutschem Windows
die Datei ohne Import-Dialog richtig öffnet.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .karte import SCHUESSE_PRO_KARTE, Karte

SPALTEN = (
    ["zeitstempel", "karten_uuid", "schuetzennummer", "nummer_quelle"]
    + [f"s{n}_{teil}" for n in range(1, SCHUESSE_PRO_KARTE + 1) for teil in ("felder", "wert")]
    + ["gesamt", "status", "bemerkung"]
)

TRENNER = ";"
ENCODING = "utf-8-sig"


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


def anhaengen(pfad: str | Path, karte: Karte) -> None:
    """Hängt eine Karte an die CSV an; legt Datei und Kopfzeile bei Bedarf an."""
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    neu = not pfad.exists() or pfad.stat().st_size == 0
    # BOM nur beim Anlegen schreiben
    with pfad.open("a", newline="", encoding=ENCODING if neu else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=TRENNER)
        if neu:
            w.writeheader()
        w.writerow(karte_als_zeile(karte))


def lesen(pfad: str | Path) -> list[dict[str, str]]:
    with Path(pfad).open(newline="", encoding=ENCODING) as f:
        return list(csv.DictReader(f, delimiter=TRENNER))
