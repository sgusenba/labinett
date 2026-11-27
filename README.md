# labinett

Auswertung der **Nikolo-Glücksscheibe** (Schützenverein Bad Zell) per USB-Webcam.
Läuft lokal unter Windows, Bedienung im Browser, Ergebnisse landen in einer CSV-Datei.

**Projektbeschreibung:** [docs/PROJEKT.md](docs/PROJEKT.md) · **Installation unter Windows:** [docs/INSTALLATION.md](docs/INSTALLATION.md) · **Auto-Update & Versionen:** [docs/UPDATE.md](docs/UPDATE.md)

## So funktioniert's

1. `labinett.exe` starten – der Browser öffnet sich mit der Oberfläche.
2. Karte unter die Kamera legen (Lage egal – verdrehte Karten werden erkannt; **dunkle Unterlage**).
   Liegt sie ruhig, wird automatisch aufgenommen und ausgewertet.
3. Werte prüfen. Mit `nummer_erfassen` zusätzlich die Schützennummer prüfen: sie
   wird aus dem Kreis gelesen und vorgeschlagen; ist sie unsicher, bleibt das Feld
   leer und die Nummer wird eingetippt.
   **Enter** speichert (Esc verwirft). Felder pro Schuss lassen sich korrigieren,
   z. B. `16+12`; leer = außerhalb.
4. Karte wegnehmen – die nächste kann kommen.

Ohne Kamera lässt sich über **Foto laden …** auch ein Handyfoto auswerten.

**Fokus:** Unter dem Live-Bild stellt der Regler die Schärfe der Webcam sofort ein
(der Wert wird als `kamera_fokus` gespeichert). **Autofokus** lässt die Kamera neu
scharfstellen und hält den gefundenen Wert nach 3 s wieder fest.

## Wertung

- Jeder Schuss zählt den Wert des getroffenen Feldes.
- Berührt das Loch eine Linie, zählen alle berührten Felder (Linie: 2, Ecke: bis zu 4).
- Außerhalb der Raute 0 – außer das Loch berührt die äußere Randlinie.
- 5 Schüsse pro Karte, Ergebnis = Summe.

Grenzfälle (Loch innerhalb der Toleranz an einer Linie), fehlende Schüsse oder
eine fehlende Nummer werden orange markiert und in der CSV mit Status `pruefen`
abgelegt.

## Feste Maße

Karte 170 × 170 mm (Format der Luftpistolenscheibe), Kaliber 4,5 mm, Feld 16 mm.
Diese Werte stehen fest in `labinett/scheibe.py` und sind nicht einstellbar.

## Einstellungen (`labinett.json` neben der .exe)

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `csv_pfad` | `ergebnisse.csv` | relativ zur .exe oder absolut |
| `kamera_index` | 0 | welche Webcam |
| `linienbreite_mm` | 0.4 | Druckstärke der Linien |
| `toleranz_mm` | 0.5 | so nah an der Berührungsgrenze → „prüfen“ |
| `anriss_toleranz_mm` | 0.0 | Anriss-Toleranz: verschiebt die Berührungsgrenze (−0,8 … +1,6 mm; negativ = strenger, positiv = großzügiger). Regler über der Auswertung, wertet die angezeigte Karte sofort neu |
| `stabile_frames` | 8 | Ruhe-Frames bis zur Auto-Aufnahme |
| `stabil_toleranz` | 0.01 | „ruhig“ = keine Rautenecke bewegt sich mehr als dieser Anteil der Diagonale |
| `belichtung_regeln` | true | nur mit `belichtung_festhalten`: festgehaltene Belichtung schrittweise kürzen, wenn mehr als 2 % des Bildes ausbrennen (z. B. Ringlicht nach dem Start eingeschaltet), bzw. verlängern, wenn eine liegende Karte zu dunkel ist |
| `beim_entnehmen_speichern` | true | Ergebnis automatisch speichern, sobald die Karte weggenommen wird – nur wenn nichts zu prüfen ist |
| `aufnahme_bilder` | 3 | so viele ruhige Bilder werden ausgewertet; die Mehrheit zählt, Abweichungen werden markiert |
| `kamera_mjpg` | true | Webcam im MJPG-Format öffnen (Full HD mit 30 statt oft nur 5 Bildern/s) |
| `kamera_festhalten` | true | Fokus nach 3 s festhalten |
| `kamera_belichtung` | null | feste Belichtung (Regler „Belichtung“ unter dem Kamerabild, wirkt sofort); `null` = Automatik. Windows: log2-Sekunden, bei Ringlicht z. B. −8 |
| `belichtung_festhalten` | false | auch Belichtung und Weißabgleich festhalten. Aus lassen: unter Windows melden viele Webcams eine falsche Belichtung, das Bild wird dann überbelichtet. Beim Start und Beenden schaltet labinett die Automatiken der Kamera wieder ein |
| `belichtung_einmessen` | true | brennt das Bild unter der Kamera-Automatik mit aufgelegter Karte aus (weiße Karte auf dunkler Unterlage, Ringlicht), misst labinett einmal je Start selbst einen festen Wert ein: so lange dunkler, bis höchstens 2 % ausbrennen. Der Wert landet in `kamera_belichtung`. Von Hand jederzeit mit **Einmessen** neben dem Belichtungsregler |
| `kamera_fokus` | -1 | fester Fokuswert der Webcam, -1 = eingeregelten Wert übernehmen (Regler in der Oberfläche setzt ihn live) |
| `nummer_erfassen` | false | Schützennummer abfragen; `false` = ohne Nummer speichern, kein „prüfen“ wegen fehlender Nummer |
| `nummer_min` / `nummer_max` | 1 / 250 | gültige Schützennummern |
| `nummer_lesen` | true | bei `nummer_erfassen`: handschriftliche Nummer automatisch lesen und vorschlagen |
| `nummern_sammeln` | true | bei `nummer_erfassen`: bestätigte Nummern-Ausschnitte in `nummern/` neben `labinett.json` ablegen (für späteres Nachtrainieren) |
| `auto_update` | true | beim Start im Hintergrund nach neuer Version suchen und laden, eingespielt beim nächsten Start ([docs/UPDATE.md](docs/UPDATE.md)) |
| `port` | 8765 | lokaler Port der Oberfläche |

## CSV

UTF-8 mit BOM, Trennzeichen `;` (öffnet direkt in Excel). Ist die Datei gesperrt
(in Excel geöffnet) oder das Ziel nicht erreichbar, landen Zeilen in
`ausstehend.jsonl` neben `labinett.json` und werden automatisch nachgetragen.
Eine vorhandene fremde CSV (andere Spalten) wird nie verändert. Eine Zeile pro Karte:

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
| `erkennung.py` + `modelle/raster_vorlage.png` | Raute finden, Lage der Karte (Feld 23) über die Feldzahlen erkennen, entzerren, Löcher finden, Nummern-Ausschnitt |
| `nummer.py` + `modelle/ziffern.onnx` | Schützennummer lesen (Kreis, Ziffern trennen, kleines CNN über OpenCV-DNN) |
| `kamera.py` | Webcam-Thread, Live-Erkennung, Auto-Aufnahme |
| `app.py` + `static/` | Web-Oberfläche und API |
| `csv_export.py` | CSV schreiben/lesen |

### Bekannte Grenzen

- Die Schützennummer wird nur vorgeschlagen, wenn alle Ziffern sicher erkannt
  sind und die Mehrheit der Aufnahmen übereinstimmt; sonst bleibt das Feld leer.
  Getestet ist sie bisher nur an echten Karten mit der Nummer 1 und an
  synthetischen mehrstelligen Nummern (`testdata/nummern/`). Die gesammelten
  Ausschnitte (`nummern/`) eignen sich als echter Testsatz bzw. zum Nachtrainieren
  (`tools/ziffern_trainieren.py`).
- Die Lage der Karte (0/90/180/270°) wird über die aufgedruckten Feldzahlen
  erkannt (Vorlage `modelle/raster_vorlage.png`, neu bauen mit
  `python tools/lage_vorlage.py`). Ist sie nicht eindeutig, erscheint ein Hinweis
  und es gilt `"extra": {"drehung": 1..3}` (90°-Schritte, Standard 0 = Feld 23 oben).
- Stark überlappende Löcher werden über die Fläche aufgeteilt; das Ziel von
  5 Schüssen hilft dabei. Ihr Mittelpunkt ist ungenauer, daher gilt für sie die
  doppelte Toleranz (`toleranz_mm`) bis „prüfen“.
