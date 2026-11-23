# Projektbeschreibung labinett

## Kurzfassung

labinett wertet die **Nikolo-Glücksscheibe** des Schützenvereins Bad Zell
automatisch aus. Eine USB-Webcam fotografiert die beschossene Karte, das
Programm erkennt die Einschusslöcher, ordnet sie den Feldern zu, berechnet das
Ergebnis nach den Anriss-Regeln und speichert es in einer CSV-Datei. Die
Bedienung erfolgt im Browser auf dem Auswerte-PC, ohne Internet.

## Hintergrund und Ziel

Beim Nikolo-Schießen schießt jede Person 5 Schüsse auf eine Glücksscheibe:
ein um 45° gedrehtes 5×5-Raster mit den Feldern 1–25. Gezählt wird nicht die
Nähe zur Mitte, sondern der aufgedruckte Feldwert. Berührt ein Loch eine
Linie, zählen alle berührten Felder (an einer Ecke bis zu vier).

Bisher werden die Karten von Hand ausgewertet. Das kostet Zeit, und an Linien
und Ecken kommt es zu Rechenfehlern oder unterschiedlichen Auslegungen – die
Testkarten zeigen mehrfach korrigierte Nebenrechnungen.

**Ziele**

- Auswertung einer Karte in wenigen Sekunden
- gleiche Regeln für alle Karten, nachvollziehbar dokumentiert
- Grenzfälle nicht still entscheiden, sondern zur Prüfung markieren
- Ergebnisliste direkt in Excel weiterverwendbar
- läuft auf einem normalen Windows-PC, ohne Installation und ohne Internet

## Wertungsregeln

1. Jeder Schuss zählt den Wert des getroffenen Feldes.
2. Berührt das Loch eine Trennlinie, zählt jedes berührte Feld voll.
3. Mehrfachtreffer im selben Feld zählen jedes Mal.
4. Außerhalb der Raute 0 – außer das Loch berührt die äußere Randlinie.
5. Ergebnis = Summe der 5 Schüsse.

## Funktionsumfang (Version 0.1)

| Bereich | Funktion |
|---|---|
| Aufnahme | Live-Bild der Webcam, automatische Aufnahme, sobald die Karte ruhig liegt; Auswertung von 3 Bildern mit Mehrheitsentscheid; Fokus/Belichtung festgehalten; manuelle Aufnahme; alternativ Foto hochladen |
| Erkennung | Raute finden und entzerren, Löcher finden, überlappende Löcher aufteilen |
| Wertung | Feldzuordnung mit Anriss-Geometrie; Kartengröße, Feldgröße und Kaliber fest, Linienbreite und Unsicher-Toleranz einstellbar |
| Kontrolle | erkannte Schüsse im Bild markiert, Grenzfälle orange, Felder pro Schuss korrigierbar |
| Schützennummer | handschriftliche Nummer wird gelesen und vorgeschlagen (nur wenn sicher), Ausschnitt wird angezeigt, sonst eintippen; gültig 1–250 |
| Ergebnisse | CSV (Excel-tauglich), Status `ok`/`pruefen`, Bemerkung, vorbereitete Spalte für Karten-UUID |
| Betrieb | eine `labinett.exe`, Einstellungen in `labinett.json`, Oberfläche unter `http://127.0.0.1:8765/` |

## Ablauf am Wettkampftag

```
Karte auflegen ─► Auto-Aufnahme ─► Erkennung + Wertung ─► Kontrolle im Browser
                                                          │ Nummer prüfen/eintippen
                                                          │ ggf. korrigieren
                                                          ▼
                       Karte wegnehmen ◄── Enter = Zeile in CSV
```

## Architektur

```
USB-Webcam
   │
   ▼
kamera.py      Kamera-Thread, Live-Erkennung der Raute, Auto-Aufnahme
   │
   ▼
erkennung.py   Raster finden → Homographie → Löcher (OpenCV)
   │  Lochpositionen in Rasterkoordinaten
   ▼
scheibe.py     Feldmatrix, Anriss-Geometrie → Felder je Schuss
karte.py       Karte mit 5 Schüssen, Summe, Status
   │
   ├──► app.py + static/index.html   Web-Oberfläche (FastAPI)
   └──► csv_export.py                ergebnisse.csv
```

### Feste Maße

Die Glücksscheibe hat immer dasselbe Format, geschossen wird immer dasselbe
Kaliber. Diese Werte sind deshalb **Konstanten im Code** (`labinett/scheibe.py`)
und keine Einstellungen:

| Maß | Wert | Herkunft |
|---|---|---|
| Karte | 170 × 170 mm | Format der Standard-Luftpistolenscheibe (ISSF 10 m) |
| Kaliber = Lochdurchmesser | 4,5 mm | immer Kaliber 4,5 mm |
| Feld (Kantenlänge) | 16,0 mm | aus den Testfotos über die Kartengröße ermittelt: die Karte ist 10,5–10,6 Feldbreiten lang → Raster 80 × 80 mm |

Verwendung:

- **Anriss-Entscheidung:** Lochradius 2,25 mm + halbe Linienbreite, umgerechnet
  mit 16 mm pro Feld in Rasterkoordinaten.
- **Lochgröße in der Erkennung:** erwartete Lochfläche im entzerrten Bild, damit
  überlappende Löcher richtig aufgeteilt werden.
- **Plausibilitätsprüfung:** Liegt die Karte vollständig im Bild, wird ihr Rand
  in Rasterkoordinaten umgerechnet. Sie muss 170 / 16 ≈ 10,6 Feldbreiten lang
  sein. Weicht eine Seite um mehr als 8 % ab, ist die Raute vermutlich falsch
  erkannt; die Karte bekommt einen Hinweis und wird geprüft.

Einstellbar bleiben nur Druckstärke der Linien (`linienbreite_mm`) und das
Unsicherheits-Band (`toleranz_mm`).

**Technik:** Python 3.12, OpenCV, FastAPI/Uvicorn, reines HTML/JavaScript ohne
Framework. Gebaut mit PyInstaller zu einer einzelnen Windows-`.exe`.
GitHub Actions testet jeden Stand und baut die `.exe`.

**Wichtige Entscheidungen**

- *Lokal statt Cloud:* keine Internetverbindung am Schießstand nötig, keine
  Personendaten außer Haus.
- *Browser als Oberfläche:* keine eigene GUI-Bibliothek, läuft auf jedem
  Windows-PC, später auch von Tablet im selben Netz denkbar.
- *Prüfen statt raten:* liegt ein Loch innerhalb einer Toleranz an einer
  Linie, wird der Schuss markiert und von einer Person bestätigt.
- *CSV statt Datenbank:* einfach, robust, direkt in Excel lesbar; Korrekturen
  werden angehängt, nichts wird überschrieben.

## Qualitätssicherung

- 52 automatische Tests: Feldmatrix, Linien-/Ecken-Regeln, Grenzfälle, CSV inkl. gesperrter Datei,
  Web-Schnittstelle, Auto-Aufnahme mit simulierter Kamera
- Erkennung gegen 7 Fotos echter Karten (`testdata/`) geprüft: Bei allen Karten
  mit eindeutiger handschriftlicher Referenz stimmt das Ergebnis exakt; bei
  zwei Karten widersprechen sich die Notizen selbst

## Stand und offene Punkte

**Erledigt:** Wertungslogik, Bilderkennung, Web-Oberfläche, CSV, Windows-Build,
[Installationsanleitung](INSTALLATION.md).

**Offen**

1. Test mit der echten Webcam am Zielrechner, Erkennung ggf. nachjustieren
2. Feldgröße (16,0 mm aus Fotos ermittelt) einmal mit dem Lineal an einer Originalkarte bestätigen
3. Schützennummer: Zuverlässigkeit an 30–50 echten Karten mit mehrstelligen Nummern messen (siehe unten)
4. QR-Code mit Karten-UUID auf den Karten (Spalte `karten_uuid` ist vorbereitet)
5. Auswertung der CSV: Rangliste, Export für Siegerehrung

### Schützennummer automatisch lesen

Die Nummer ist handgeschrieben, höchstens dreistellig, gültig sind 1–250.

- Kreis finden, Innenfläche ausschneiden, Ziffern trennen (zerfallene Ziffern
  zusammenführen, zusammenhängende an der dünnsten Stelle trennen).
- Jede Ziffer mit einem kleinen Modell (ONNX über `cv2.dnn`, offline, steckt in
  der `.exe`) klassifizieren.
- Nicht Ziffer für Ziffer entscheiden, sondern die **wahrscheinlichste gültige
  Nummer 1–250** wählen. Das schließt z. B. „3xx“ oder „0x“ von selbst aus.
- Mehrere ruhige Bilder abstimmen. Ab einer Schwelle gilt die Nummer als
  erkannt, sonst wird sie nur vorgeschlagen und die Person bestätigt bzw.
  tippt drüber. Lieber nachfragen als eine falsche Nummer speichern.
- Bestätigte Ausschnitte werden gesammelt, damit das Modell nachtrainiert
  werden kann.
- Voraussetzung: 30–50 Karten mit gut lesbarer Nummer als Testsatz, sonst
  lässt sich die Zuverlässigkeit nicht messen.

**Umgesetzt** (`labinett/nummer.py`) wie oben beschrieben, mit diesen Details:

- Modell: kleines CNN, trainiert mit `tools/ziffern_trainieren.py` auf MNIST,
  so verfremdet, dass es wie die Kamera-Ausschnitte aussieht, dazu synthetische
  „1“ mit langem Aufstrich (so schreibt man hier, in MNIST selten) und eine
  Klasse „keine einzelne Ziffer“ (zwei sich berührende Ziffern, Bruchstücke).
  Damit werden zusammenhängende Ziffern über das Netz getrennt.
- Ein Vorschlag erscheint nur, wenn jede Ziffer sicher ist und die Mehrheit der
  3 Aufnahmen dieselbe Nummer liest; sonst bleibt das Feld leer, mit Hinweis.
- Bestätigte Ausschnitte landen in `nummern/<nummer>_<zeit>_<auto|manuell>.png`.
- Bisher geprüft: alle echten Testkarten (Nummer 1 bzw. leer) und 40 synthetische
  mehrstellige Nummern (`testdata/nummern/`, aus `tools/nummern_testsatz.py`).
  Der echte Testsatz mit mehrstelligen Nummern steht noch aus.

## Projektdaten

| | |
|---|---|
| Repository | <https://github.com/sgusenba/labinett> |
| Verantwortlich | DI Stefan Gusenbauer |
| Einsatz | Nikolo-Schießen, Schützenverein Bad Zell |
| Zielsystem | Windows 10/11, USB-Webcam |
| Lizenz | noch festzulegen |
