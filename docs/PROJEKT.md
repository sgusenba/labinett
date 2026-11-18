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
| Aufnahme | Live-Bild der Webcam, automatische Aufnahme, sobald die Karte ruhig liegt; manuelle Aufnahme; alternativ Foto hochladen |
| Erkennung | Raute finden und entzerren, Löcher finden, überlappende Löcher aufteilen |
| Wertung | Feldzuordnung mit Anriss-Geometrie (Lochdurchmesser, Linienbreite, Feldgröße einstellbar) |
| Kontrolle | erkannte Schüsse im Bild markiert, Grenzfälle orange, Felder pro Schuss korrigierbar |
| Schützennummer | Ausschnitt des Nummernkreises wird angezeigt, Nummer wird eingetippt |
| Ergebnisse | CSV (Excel-tauglich), Status `ok`/`pruefen`, Bemerkung, vorbereitete Spalte für Karten-UUID |
| Betrieb | eine `labinett.exe`, Einstellungen in `labinett.json`, Oberfläche unter `http://127.0.0.1:8765/` |

## Ablauf am Wettkampftag

```
Karte auflegen ─► Auto-Aufnahme ─► Erkennung + Wertung ─► Kontrolle im Browser
                                                          │ Nummer eintippen
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

- 33 automatische Tests: Feldmatrix, Linien-/Ecken-Regeln, Grenzfälle, CSV,
  Web-Schnittstelle, Auto-Aufnahme mit simulierter Kamera
- Erkennung gegen 7 Fotos echter Karten (`testdata/`) geprüft: Bei allen Karten
  mit eindeutiger handschriftlicher Referenz stimmt das Ergebnis exakt; bei
  zwei Karten widersprechen sich die Notizen selbst

## Stand und offene Punkte

**Erledigt:** Wertungslogik, Bilderkennung, Web-Oberfläche, CSV, Windows-Build,
[Installationsanleitung](INSTALLATION.md).

**Offen**

1. Test mit der echten Webcam am Zielrechner, Erkennung ggf. nachjustieren
2. Feldgröße an einer Originalkarte messen und als Standard eintragen
3. QR-Code mit Karten-UUID und Schützennummer auf den Karten – ersetzt das
   Eintippen der Nummer
4. Auswertung der CSV: Rangliste, Export für Siegerehrung
5. Optional: Kamera-Drehung automatisch erkennen

## Projektdaten

| | |
|---|---|
| Repository | <https://github.com/sgusenba/labinett> |
| Verantwortlich | DI Stefan Gusenbauer |
| Einsatz | Nikolo-Schießen, Schützenverein Bad Zell |
| Zielsystem | Windows 10/11, USB-Webcam |
| Lizenz | noch festzulegen |
