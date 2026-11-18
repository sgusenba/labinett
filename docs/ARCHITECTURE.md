# Architektur – Nikolo-Scheibe auswerten (Python + Web-Bedienung)

Spec: [`spec/nikolo-auswertung-live2.html`](../spec/nikolo-auswertung-live2.html) – funktionierender Browser-Prototyp.
Ziel: Ein Windows-Rechner mit USB-Webcam erkennt aufgelegte Karten **automatisch**, zählt die Punkte und liest die **Schützennummer** im Kreis (bei Unsicherheit von Hand eintragen) und schreibt die Ergebnisse in eine **CSV-Datei** (Speicherort einstellbar). Die **UUID aus einem QR-Code** ist vorbereitet, kommt aber erst später, wenn die Karten QR-Codes haben. Bedienung im Browser, Auslieferung als **.exe**.

## Rahmen

| | Entscheidung | Grund |
|---|---|---|
| Plattform | Windows 10/11, ein Rechner, USB-Webcam | Einsatz am Schießstand |
| Backend | Python 3.12, OpenCV, FastAPI + Uvicorn | OpenCV steuert die Kamera direkt und rechnet schnell; FastAPI liefert UI und API |
| Bedienung | Web-UI (HTML + Vanilla-JS) auf `http://127.0.0.1:8765` | Bekannte Oberfläche aus der Spec, kein Framework, kein Build-Schritt |
| Speicher | CSV-Datei (`;`, UTF-8 mit BOM, Excel-tauglich), Pfad einstellbar | Wunsch; direkt in Excel öffnen |
| Identität | Schritt 1: Schützennummer (automatisch gelesen, sonst eingetippt). Später zusätzlich UUID aus dem QR-Code | Heutige Karten haben noch keinen QR-Code |
| Ziffernerkennung | Lokal, offline: Kreis finden → Ziffern trennen → kleines ONNX-Modell über `cv2.dnn` | Kein Internet, keine Zusatzinstallation (kein Tesseract nötig), passt in die exe |
| Schüsse | Jede Karte hat genau 5 Schüsse | Grundlage für automatische Aufnahme und Prüfung |
| Auslieferung | PyInstaller `onedir` + Startmenü-/Desktop-Verknüpfung, gebaut über GitHub Actions | Kein Python nötig am Zielrechner; `onedir` startet schneller und löst seltener Virenscanner-Fehlalarme aus als `onefile` |
| Netzwerk | Nur `127.0.0.1`, kein Internet nötig | Offline am Schießstand, keine Freigaben in der Firewall |

## Komponenten

```mermaid
flowchart LR
  subgraph Python-Prozess
    CAM[camera.py<br/>Kamera-Thread<br/>Frames + Einstellungen] --> PIPE[live.py<br/>Analyse-Thread<br/>~8–10 Bilder/s]
    PIPE --> TR[tracker.py<br/>Ruhe-Erkennung<br/>Zustandsmaschine]
    TR -->|stabil| CAPT[capture.py<br/>Aufnahme volle Auflösung<br/>Schüsse + Nummer + Kennung]
    CAPT --> STORE[storage.py<br/>CSV]
    subgraph vision
      GRID[grid.py] --> WARP[warp.py] --> SHOTS[shots.py] --> BOARD[board.py]
      CIRC[circle.py] --> NUM[number.py]
      QR["qr.py (später)"]
    end
    PIPE -.nutzt.-> vision
    CAPT -.nutzt.-> vision
    API[server.py<br/>FastAPI]
  end
  API <-->|REST, MJPEG, SSE| UI[Browser<br/>web/index.html]
  CAM --> API
  TR --> API
  CAPT --> API
  STORE --> API
```

### Paketstruktur

```
labinett/
  nikolo/
    __main__.py      Start: Server hochfahren, Browser öffnen
    config.py        Einstellungen (config.toml in %APPDATA%\Nikolo): Kamera, Drehung, CSV-Pfad, Schwellen
    camera.py        cv2.VideoCapture (CAP_DSHOW), Auflösung, Fokus/Belichtung/Weißabgleich sperren
    live.py          Analyse-Schleife: Frame verkleinern → vision → tracker → Overlay
    tracker.py       Ruhe-Erkennung und Zustände (siehe unten)
    capture.py       aktuelle Aufnahme: Bilder, Ecken, Schüsse, Nummer, Kennung, Korrekturen, Neuberechnung
    identity.py      Kennungsquellen hinter einer Schnittstelle (siehe „Kennung“)
    storage.py       CSV lesen/anhängen/löschen, Sperre durch Excel erkennen
    server.py        FastAPI-Routen, MJPEG-Stream, Server-Sent Events
    vision/
      board.py       Feldbelegung, Bewertung, Sicherheit (1:1 aus der Spec)
      grid.py        Papier → Raster-Raute → 4 Ecken (Linien-Fit), Plausibilitätsprüfung
      warp.py        Homographie, begradigtes 720×720-Bild
      shots.py       Löcher finden, überlagerte Löcher per k-means trennen
      circle.py      Kreis mit der Schützennummer finden (aus der Spec)
      number.py      Ziffern im Kreis trennen und lesen, Sicherheit je Ziffer
      qr.py          UUID aus dem QR-Code (cv2.QRCodeDetector) – vorbereitet, standardmäßig aus
    models/
      digits.onnx    Ziffernmodell (wenige hundert kB), mit Trainingsskript in tools/
  tools/
    train_digits.py  Modell aus gesammelten Ziffernausschnitten + Schriften trainieren
  web/
    index.html, app.js, style.css
  tests/
    synth.py         synthetische Scheiben (verdreht, verrauscht)
    fixtures/        echte Fotos + erwartete Ergebnisse (*.json)
    test_*.py        pytest
  packaging/
    nikolo.spec      PyInstaller
  .github/workflows/
    build-windows.yml  Tests + exe bauen, bei Tag als Release-Datei
  spec/              HTML-Prototyp (Referenz)
  docs/
```

Regel: `vision/` ist reine Logik (NumPy-Arrays rein, Ergebnisse raus), ohne Kamera, Threads oder HTTP. Damit lässt sie sich mit Fotos testen.

## Übernahme der Erkennung aus der Spec

Der Algorithmus bleibt gleich. OpenCV ersetzt die handgeschriebenen Bausteine:

| Spec (JS) | Python |
|---|---|
| `otsu`, Schwellwerte | `cv2.threshold(..., THRESH_OTSU)` + gleiche Klemmen (60–150 bzw. 60–130) |
| `label` | `cv2.connectedComponentsWithStats` |
| `opening` | `cv2.morphologyEx(MORPH_OPEN)` mit quadratischem Kern |
| Löcher füllen (Rand-Komponenten) | `cv2.floodFill` vom Rand bzw. Konturen mit `RETR_EXTERNAL` |
| `homography`, `normalize` | `cv2.getPerspectiveTransform` + `cv2.warpPerspective` |
| `fitSide` | gleiche Logik in NumPy (äußerste Punkte je Abschnitt, `cv2.fitLine`) |
| k-means für Doppellöcher | `cv2.kmeans` |
| `findCircle` | 1:1 portiert, Komponenten über `cv2.connectedComponentsWithStats` |
| Nummer lesen über Claude | lokal: `number.py` + `digits.onnx` (siehe unten) |
| jsQR | `cv2.QRCodeDetector` (später) |
| `score` | 1:1 portiert |

Die magischen Zahlen (`.045*S`, `.058`, `.09`, Klemmen …) wandern dokumentiert in `config.py` (`DetectionConfig`).

## Schützennummer lesen

1. **Kreis finden** wie in der Spec (ringförmige dunkle Komponente außerhalb des Rasters).
2. **Innenfläche ausschneiden**, auf feste Größe bringen, Schwellwert (adaptiv), Kreisring entfernen.
3. **Ziffern trennen** über Komponenten, von links nach rechts; **1–3 Ziffern**, handgeschrieben. Zerfallene Ziffern (z. B. eine 4 oder 5 aus zwei Strichen) werden über Überlappung in x zusammengeführt, zusammenhängende Ziffern über die Breite (> 1,4× typische Ziffernbreite) an der dünnsten Stelle getrennt. Mehr als 3 Teile → unsicher.
4. **Jede Ziffer klassifizieren** mit einem kleinen CNN (`digits.onnx`, über `cv2.dnn`, keine Zusatzbibliothek). Ausgabe: Ziffer + Wahrscheinlichkeit. Zusätzlich werden die zwei besten Trennungen bewertet; liegen sie nah beieinander, gilt die Nummer als unsicher.
5. **Mehrere Bilder abstimmen:** Die Nummer wird in den letzten ruhigen Livebildern und in der Aufnahme gelesen. Stimmen sie überein, steigt die Sicherheit.
6. **Sicherheit** = kleinste Ziffern-Wahrscheinlichkeit × Übereinstimmung. Ab einer Schwelle (Standard 90 %) gilt die Nummer als erkannt; darunter wird sie nur vorgeschlagen und das Eingabefeld bekommt den Fokus.

**Handschrift – realistische Erwartung:** Einzelne handgeschriebene Ziffern erkennt ein gutes Modell zu etwa 98–99 %, eine dreistellige Nummer also zu ~95 %. Schwierig sind 1/7, 4/9, 3/5 und Ziffern, die den Kreisring berühren. Deshalb:

- **Lieber nachfragen als falsch speichern:** Die Schwelle für „sicher“ wird an echten Karten so eingestellt, dass praktisch keine falschen Nummern automatisch gespeichert werden. Am Anfang wird öfter nachgefragt.
- **Modell:** Start mit EMNIST-Ziffern (Handschrift, ~280 000 Beispiele), mit Verzerrung, Strichstärke, Unschärfe und Rauschen aufbereitet, damit es zu Kugelschreiber/Filzstift auf Karton passt. Sobald echte Karten durchlaufen, speichert die App die Ausschnitte samt bestätigter Nummer in `%APPDATA%\Nikolo\samples\`; daraus wird nachtrainiert. Das Modell ist austauschbar, ohne Code zu ändern.
- **Plausibilität:** optional eine Teilnehmerliste (CSV mit gültigen Nummern) oder ein Nummernbereich in den Einstellungen. Eine gelesene Nummer, die es nicht gibt, gilt als unsicher; bei knappen Fällen gewinnt die gültige Variante.
- **Hilfe am Papier:** Ziffern groß, ohne Berührung des Kreisrings und ohne Durchstreichen schreiben lassen. Das bringt mehr als jedes Modell.

Fallback, wenn kein Kreis gefunden wird: Feld leer, Fokus ins Eingabefeld, Ausschnitt des Fotos rund um das Raster zur Orientierung.

## Kennung (Nummer heute, UUID später)

Die Karte bekommt eine **Kennung** aus einer oder mehreren Quellen:

```python
class IdentitySource(Protocol):
    name: str                                   # "number", "qr"
    def read(self, photo, analysis) -> Reading | None   # Wert + Sicherheit
```

- **Schritt 1:** nur `NumberSource` aktiv. Kennung = Schützennummer.
- **Später:** `QrSource` per Einstellung `identity.qr = true` einschalten. Dann gilt: UUID als Schlüssel, Nummer zur Kontrolle. Wird der QR in der Aufnahme nicht gefunden, durchsuchen die nächsten Livebilder noch ~2 s weiter. Lassen sich UUID → Nummer zuordnen, wird ein Widerspruch als Hinweis angezeigt.
- CSV, API und UI haben die Spalte/das Feld **UUID von Anfang an**; bis QR aktiv ist, bleibt es leer bzw. ausgeblendet. So muss beim Umstieg nichts migriert werden.

## Live-Modus ohne Springen

Ursachen fürs Springen im Prototyp: Die Webcam stellt Fokus und Belichtung laufend nach, jedes Bild wird unabhängig ausgewertet, und die Anzeige wechselt bei „Raster weg“ Größe und Inhalt.

1. **Kamera fixieren:** Autofokus, Belichtung und Weißabgleich nach dem Einrichten sperren (`CAP_PROP_AUTOFOCUS`, `CAP_PROP_FOCUS`, `CAP_PROP_AUTO_EXPOSURE`, `CAP_PROP_EXPOSURE`). In der UI: „Kamera einrichten“ mit Reglern; Werte landen in `config.toml`. Fallback: Treiber-Dialog über `CAP_PROP_SETTINGS`.
2. **Anzeige ruhig:** Das Livebild hat immer dieselbe Größe. Raster und Löcher werden als Overlay eingezeichnet, die Ecken geglättet (gleitender Mittelwert, bei großen Sprüngen zurückgesetzt).
3. **Auswertung erst nach Ruhe:** siehe Tracker.

**Webcam:** Wird später festgelegt. Darum allgemein für UVC-Webcams gebaut: Kamera und Auflösung in der UI wählbar, Regler nur für die Eigenschaften, die die Kamera meldet. Gut geeignet ist eine Kamera mit manuell einstellbarem Fokus und mindestens 1080p. Ein Stativ oder Arm senkrecht über der Ablage hilft mehr als jede Software.

## Tracker und automatische Aufnahme

```mermaid
stateDiagram-v2
  [*] --> Suchen
  Suchen --> Messen: Raster erkannt
  Messen --> Suchen: Raster weg
  Messen --> Aufnahme: ruhig ≥ 1 s und Ergebnis-Mehrheit und 5 Schüsse
  Aufnahme --> Prüfen: Auswertung in voller Auflösung
  Prüfen --> Warten: gespeichert / verworfen
  Prüfen --> Prüfen: Korrektur (Schuss, Ecken, Toleranz)
  Warten --> Suchen: Karte ≥ 0,5 s entnommen
```

- **Ruhig:** Über die letzten ~8 Analysebilder bewegt sich keine Ecke mehr als ~1 % der Rasterdiagonale.
- **Ergebnis-Mehrheit:** Mindestens 75 % dieser Bilder liefern dieselbe Signatur (Anzahl Schüsse + sortierte Werte). Kippt ein Schuss an der Linie hin und her, wird trotzdem aufgenommen; der Schuss erscheint dann gelb/rot.
- **Aufnahme:** Bild in voller Auflösung, optional Mittel aus 3 Bildern gegen Rauschen. Dann Raster, Schüsse, Schützennummer (abgestimmt mit den letzten Livebildern), später zusätzlich QR.
- **Sperre:** Nach einer Aufnahme erst wieder auslösen, wenn die Karte entnommen war. Ein ungespeichertes Ergebnis wird nie automatisch überschrieben.
- **Nicht genau 5 Schüsse erkannt:** keine automatische Aufnahme, Hinweis + Knopf „Jetzt aufnehmen“. Nach dem Aufnehmen muss die Anzahl per Klick auf 5 gebracht werden, sonst ist Speichern gesperrt.

## Web-API

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/` | Web-UI |
| GET | `/api/live.mjpg` | Livebild mit Overlay (MJPEG, als `<img>` einbindbar) |
| GET | `/api/events` | Server-Sent Events: Zustand, Fortschritt, Hinweistext, neue Aufnahme |
| GET | `/api/capture` | aktuelle Aufnahme: Schüsse, Felder, Werte, Sicherheit, Nummer + Sicherheit, UUID, Hinweise |
| GET | `/api/capture/warped.jpg`, `/api/capture/photo.jpg`, `/api/capture/number.jpg` | Bilder dazu (Nummernausschnitt zum Ablesen) |
| POST | `/api/capture/number/reread` | Nummer neu lesen |
| POST | `/api/capture/snap` | sofort aufnehmen |
| POST | `/api/capture/shots` | Schuss hinzufügen/entfernen (Feldkoordinaten) |
| POST | `/api/capture/corners` | Ecken manuell setzen |
| POST | `/api/capture/tolerance` | Anriss-Toleranz ändern |
| POST | `/api/capture/save` | mit Nummer (und später UUID) in die CSV schreiben, Werte bei Bedarf von Hand korrigiert |
| DELETE | `/api/capture` | verwerfen |
| GET / DELETE | `/api/results`, `/api/results/{id}` | gespeicherte Karten |
| GET | `/api/results.csv` | CSV herunterladen |
| GET / PUT | `/api/settings`, GET `/api/cameras` | Kamera, Auflösung, Drehung, automatisch speichern, Fokus/Belichtung, CSV-Pfad, Nummern-Schwelle, Nummernbereich/Teilnehmerliste, QR an/aus |
| POST | `/api/settings/csv/browse` | Windows-Dialog „Speichern unter“ öffnen und Pfad übernehmen |

Bewertung und Korrekturen rechnet nur der Server – eine Quelle der Wahrheit.

## Bedienablauf

1. `Nikolo.exe` starten → Browser öffnet sich, Livebild läuft.
2. Karte aufrecht (23 oben) unter die Kamera legen → Raster wird grün, Fortschrittsbalken läuft → automatische Aufnahme.
3. **Automatisch speichern** (Standard): Sind 5 Schüsse erkannt, alle Schüsse grün und die Schützennummer sicher erkannt, wird sofort in die CSV geschrieben. Die UI zeigt Nummer und Ergebnis groß an, mit einem Knopf „Rückgängig“ für die letzte Karte.
4. Sonst bleibt das Ergebnis zur Prüfung stehen (gelb/rote Schüsse, Nummer unsicher oder nicht gefunden). Der Nummernausschnitt wird groß gezeigt, der Vorschlag steht im Feld und ist markiert, sodass man einfach drübertippt. Klick ins Bild korrigiert Schüsse. **Enter** speichert, **Esc** verwirft.
5. Karte wegnehmen, nächste auflegen.

## CSV

**Speicherort einstellbar:** In den Einstellungen der UI per Pfadfeld oder Windows-Dialog „Speichern unter“ (öffnet der Python-Prozess, der ja lokal läuft). Gespeichert in `config.toml`. Standard: `Dokumente\Nikolo\nikolo-ergebnisse.csv`. Auch Netzlaufwerk oder USB-Stick sind möglich.

- Beim Wechseln wird geprüft, ob der Ordner beschreibbar ist. Gibt es die Datei schon mit passendem Kopf, wird angehängt; sonst neu angelegt. Eine vorhandene Datei mit fremdem Kopf wird nie überschrieben.
- Ist das Ziel nicht erreichbar (Stick abgezogen, Netzlaufwerk weg) oder die Datei in Excel geöffnet (Windows sperrt sie), landen Ergebnisse in einer Warteschlange (`%APPDATA%\Nikolo\pending.jsonl`) und werden nachgetragen, sobald es wieder geht. Die UI zeigt das deutlich an.

```
ID;Datum;Schützennummer;Nummer erkannt;UUID;Schuss 1;Schuss 2;Schuss 3;Schuss 4;Schuss 5;Gesamt;Korrigiert
```

- Neue Ergebnisse werden **angehängt**; Löschen schreibt die Datei neu.
- `Nummer erkannt` = `auto` oder `manuell`. `UUID` bleibt leer, bis QR-Codes eingeführt sind.
- Gleiche Schützennummer schon gespeichert: Hinweis (z. B. „Nr. 17 hat schon 2 Karten“), Speichern bleibt möglich, weil eine Person mehrere Karten schießen kann. Mit QR: doppelte UUID = gleiche Karte → kein automatisches Speichern, nur nach Bestätigung.
- `Korrigiert` = ja, wenn Schüsse oder Ecken von Hand geändert wurden.

## Tests

- **Unit:** `board.score` (Feldmitte, Linie, Kreuzung, außerhalb, Doppelloch-Obergrenze), Tracker-Zustände, CSV-Rundlauf, Kennungsquellen (QR aus → UUID leer).
- **Nummer:** Ziffern-Testsatz aus echten Ausschnitten; Ziel ≥ 99 % richtig bei „sicher“, Rest landet bei „bitte prüfen“ statt falsch gespeichert.
- **Synthetisch:** Generator für Scheiben mit bekannten Löchern, Drehung ±10°, leichte Perspektive, Rauschen.
- **Golden:** echte Fotos von der verwendeten Webcam in `tests/fixtures/` mit erwarteten Werten. Jede Änderung an Schwellen muss sie bestehen.
- Läuft in GitHub Actions auf Windows vor jedem exe-Build.

## Meilensteine

1. **Grundgerüst + Erkennung:** Paket, `vision/` portiert, synthetische Tests, Kommandozeile `python -m nikolo.vision foto.jpg`.
2. **Golden-Tests:** 5–10 echte Fotos mit Ergebnissen, Schwellen abgleichen.
3. **Kamera + Live:** Kamera-Thread, MJPEG mit Overlay, Tracker, automatische Aufnahme, Kamera fixieren.
4. **Schützennummer:** Kreis, Ziffern trennen, erstes Modell, Abstimmung über mehrere Bilder, Ausschnitte sammeln.
5. **Web-UI + CSV:** Ergebnis prüfen/korrigieren, Nummer bestätigen/eintippen, speichern, Liste, Einstellungen.
6. **exe:** PyInstaller, GitHub-Action, Release-Datei, Kurzanleitung.
7. **Später – QR/UUID:** `QrSource` einschalten, sobald die Karten QR-Codes haben; Übergabe an das Wettkampfsystem über die UUID.

## Geklärt

- Webcam: wird später festgelegt → allgemein für UVC-Kameras gebaut.
- Jede Karte hat genau 5 Schüsse.
- Schritt 1: Schützennummer automatisch lesen, sonst eintippen. QR/UUID ist vorbereitet, kommt später.
- CSV-Speicherort ist einstellbar.

- Schützennummer ist handgeschrieben, höchstens 3-stellig.

## Offen

- Gibt es eine Teilnehmerliste oder einen festen Nummernbereich, gegen den geprüft werden kann?
