# labinett

Auswertung der **Nikolo-Glücksscheibe** (Schützenverein Bad Zell) per USB-Webcam.
Läuft lokal unter Windows, Bedienung im Browser, Ergebnisse landen in einer CSV-Datei.

**Installation unter Windows:** siehe [docs/INSTALLATION.md](docs/INSTALLATION.md).

## So funktioniert's

1. `labinett.exe` starten – der Browser öffnet sich mit der Oberfläche.
2. Karte unter die Kamera legen (aufrecht, Feld 23 oben, **dunkle Unterlage**).
   Liegt sie ruhig, wird automatisch aufgenommen und ausgewertet.
3. Schützennummer aus dem eingeblendeten Kreis eintippen, Werte prüfen,
   **Enter** speichert (Esc verwirft). Felder pro Schuss lassen sich korrigieren,
   z. B. `16+12`; leer = außerhalb.
4. Karte wegnehmen – die nächste kann kommen.

Ohne Kamera lässt sich über **Foto laden …** auch ein Handyfoto auswerten.

## Wertung

- Jeder Schuss zählt den Wert des getroffenen Feldes.
- Berührt das Loch eine Linie, zählen alle berührten Felder (Linie: 2, Ecke: bis zu 4).
- Außerhalb der Raute 0 – außer das Loch berührt die äußere Randlinie.
- 5 Schüsse pro Karte, Ergebnis = Summe.

Grenzfälle (Loch innerhalb der Toleranz an einer Linie), fehlende Schüsse oder
eine fehlende Nummer werden orange markiert und in der CSV mit Status `pruefen`
abgelegt.

## Einstellungen (`labinett.json` neben der .exe)

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `csv_pfad` | `ergebnisse.csv` | relativ zur .exe oder absolut |
| `kamera_index` | 0 | welche Webcam |
| `feldgroesse_mm` | 15.0 | Kantenlänge eines Feldes – **bitte an einer Karte nachmessen** |
| `lochdurchmesser_mm` | 4.5 | Luftgewehr |
| `linienbreite_mm` | 0.4 | Druckstärke der Linien |
| `toleranz_mm` | 0.5 | so nah an der Berührungsgrenze → „prüfen“ |
| `stabile_frames` | 8 | Ruhe-Frames bis zur Auto-Aufnahme |
| `port` | 8765 | lokaler Port der Oberfläche |

## CSV

UTF-8 mit BOM, Trennzeichen `;` (öffnet direkt in Excel). Eine Zeile pro Karte:

```
zeitstempel;karten_uuid;schuetzennummer;nummer_quelle;s1_felder;s1_wert;…;s5_felder;s5_wert;gesamt;status;bemerkung
```

`karten_uuid` ist für spätere QR-Codes vorbereitet und derzeit leer.

## Entwicklung

```bash
pip install -r requirements-dev.txt
pytest -q                 # inkl. Erkennung auf den Fotos in testdata/
python -m labinett        # Server starten
pyinstaller labinett.spec # baut dist/labinett(.exe)
```

Die Windows-`.exe` baut GitHub Actions bei jedem Push auf `main`
(Actions → letzter Lauf → Artefakt `labinett-windows`). Ein Versions-Tag
(`git tag v0.1.1 && git push origin v0.1.1`) legt zusätzlich ein Release mit der
`.exe` an, das ohne GitHub-Konto heruntergeladen werden kann.

### Aufbau

| Modul | Aufgabe |
|---|---|
| `scheibe.py` | Feldmatrix, Geometrie, Wertung eines Schusses |
| `karte.py` | Datenmodell Karte/Schuss, Status „prüfen“ |
| `erkennung.py` | Raute finden, entzerren, Löcher finden, Nummern-Ausschnitt |
| `kamera.py` | Webcam-Thread, Live-Erkennung, Auto-Aufnahme |
| `app.py` + `static/` | Web-Oberfläche und API |
| `csv_export.py` | CSV schreiben/lesen |

### Bekannte Grenzen

- Die handschriftliche Schützennummer wird nicht automatisch gelesen
  (Ausschnitt wird angezeigt, Nummer eintippen). Kommt mit den QR-Codes.
- Die Karte muss aufrecht liegen; für eine gedrehte Kamera gibt es
  `"extra": {"drehung": 1..3}` (90°-Schritte).
- Stark überlappende Löcher werden über die Fläche aufgeteilt; das Ziel von
  5 Schüssen hilft dabei. Solche Schüsse kurz prüfen.
