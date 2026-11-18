# labinett unter Windows installieren

Diese Anleitung richtet labinett auf dem Auswerte-PC ein (Windows 10 oder 11).
Dauer: ca. 15 Minuten. Admin-Rechte sind nicht nötig.

## Was du brauchst

- Windows-PC oder -Laptop
- USB-Webcam (möglichst Full HD, mit Autofokus)
- Halterung, damit die Webcam senkrecht von oben auf die Karte schaut
  (z. B. Schwanenhals- oder Stativarm, ca. 25–40 cm Abstand)
- **Dunkle, matte Unterlage** (schwarzer Karton, dunkles Tuch) – durch die
  Einschusslöcher muss es dunkel durchscheinen
- Gleichmäßiges Licht ohne harte Schatten oder Spiegelungen

## 1. Programm herunterladen

**Variante A – fertige Version (empfohlen)**

1. Im Browser öffnen: <https://github.com/sgusenba/labinett/releases>
2. Bei der neuesten Version unter *Assets* auf **`labinett.exe`** klicken.
3. Einen eigenen Ordner anlegen, z. B. `C:\labinett`, und die `labinett.exe`
   dorthin verschieben.
   Nicht im Download-Ordner lassen: In diesem Ordner landen später auch die
   Einstellungen (`labinett.json`) und die Ergebnisse (`ergebnisse.csv`).

**Variante B – Entwicklungsstand (braucht GitHub-Anmeldung)**

1. <https://github.com/sgusenba/labinett/actions> öffnen, oben den letzten
   grünen Lauf von *CI* anklicken.
2. Unten bei *Artifacts* **`labinett-windows`** herunterladen (ZIP).
3. ZIP entpacken und `labinett.exe` nach `C:\labinett` verschieben.

## 2. Webcam anschließen und freigeben

1. Webcam einstecken, Windows installiert den Treiber automatisch.
2. **Einstellungen → Datenschutz und Sicherheit → Kamera** (Windows 10: **Datenschutz → Kamera**):
   - *Kamerazugriff* **Ein**
   - *Desktop-Apps den Zugriff auf Ihre Kamera erlauben* **Ein**
3. Andere Programme schließen, die die Kamera benutzen (Teams, Zoom, Kamera-App) –
   eine Webcam kann immer nur ein Programm gleichzeitig nutzen.

## 3. Erster Start

1. `C:\labinett\labinett.exe` doppelklicken.
2. **Windows-SmartScreen** meldet beim ersten Mal „Der Computer wurde durch
   Windows geschützt“, weil das Programm nicht signiert ist:
   **Weitere Informationen → Trotzdem ausführen**.
3. Ein schwarzes Konsolenfenster öffnet sich – **offen lassen**, das ist das
   Programm. Kurz danach öffnet sich der Browser mit
   <http://127.0.0.1:8765/>.
4. Fragt die Windows-Firewall nach, darf der Zugriff **abgelehnt** werden –
   labinett läuft nur lokal auf diesem PC.

Im Ordner `C:\labinett` liegt jetzt eine `labinett.json` mit den Einstellungen.

Beenden: Konsolenfenster schließen (oder dort `Strg+C`).

## 4. Einrichten

Im Browser unten links **Einstellungen** aufklappen:

| Einstellung | Was tun |
|---|---|
| **Kamera-Nr.** | Zeigt das Live-Bild die falsche Kamera (z. B. die eingebaute Laptop-Kamera), auf `1` oder `2` stellen. |
| **Feldgröße (mm)** | Mit einem Lineal die **Kantenlänge eines einzelnen Feldes** auf der Karte messen (entlang einer Linie, nicht quer über die Raute) und eintragen. Wichtig für die Entscheidung, ob ein Loch eine Linie berührt. |
| **CSV-Datei** | Speicherort der Ergebnisse, z. B. `C:\Users\<Name>\Desktop\nikolo-2026.csv`. Ohne Pfad landet die Datei neben der `labinett.exe`. |

**Speichern** klicken. Kamera-Nummer und Auflösung wirken erst nach einem
Neustart des Programms.

## 5. Kamera ausrichten und testen

1. Unterlage unter die Kamera legen, eine bereits geschossene Karte darauf –
   **aufrecht**, Feld 23 zeigt nach oben (weg von dir).
2. Im Live-Bild muss die ganze Karte zu sehen sein, mit etwas Rand.
3. Wird die Raute erkannt, erscheint ein Rahmen:
   **gelb/orange** = erkannt, wartet auf Ruhe · **grün** = aufgenommen.
4. Rechts erscheint die Auswertung. Ergebnis mit der Karte vergleichen.

Klappt das, ist die Installation fertig.

## Bedienung am Wettkampftag (Kurzfassung)

1. Karte auflegen → wird automatisch aufgenommen.
2. Schützennummer aus dem angezeigten Kreis eintippen.
3. Orange markierte Schüsse prüfen, ggf. Felder korrigieren (z. B. `16+12`,
   leer = außerhalb).
4. **Enter** = speichern, **Esc** = verwerfen.
5. Karte wegnehmen, nächste auflegen.

Die CSV öffnet sich direkt in Excel. Während des Wettkampfs die CSV am besten
nicht in Excel offen lassen – Excel sperrt die Datei, dann kann labinett nicht
speichern. Für einen Zwischenstand eine Kopie öffnen.

## Probleme und Lösungen

| Problem | Lösung |
|---|---|
| „Kamera 0 lässt sich nicht öffnen“ | Kamera-Freigabe (Schritt 2) prüfen, andere Kamera-Programme schließen, andere Kamera-Nr. probieren, Programm neu starten. |
| Live-Bild bleibt schwarz | USB-Port wechseln (direkt am PC, nicht am Hub), Programm neu starten. |
| Raute wird nicht erkannt | Ganze Karte im Bild? Licht gleichmäßig? Spiegelungen vermeiden, Kamera etwas höher setzen. |
| Löcher werden nicht oder falsch erkannt | Unterlage muss dunkel sein. Unscharfes Bild → Fokus der Webcam prüfen. |
| Viele Schüsse orange | Feldgröße nachmessen und korrekt eintragen. |
| „Port 8765 ist belegt“ | labinett läuft schon – das andere Konsolenfenster benutzen oder schließen. |
| Speichern schlägt fehl | Ist die CSV in Excel geöffnet? Schließen und nochmal speichern. |
| Browser geht nicht auf | Manuell <http://127.0.0.1:8765/> öffnen. |

## Update auf eine neue Version

1. Programm beenden.
2. Neue `labinett.exe` herunterladen (Schritt 1) und die alte in `C:\labinett`
   ersetzen. `labinett.json` und die CSV bleiben erhalten.

## Optional: Verknüpfung auf dem Desktop

Rechtsklick auf `labinett.exe` → **Weitere Optionen anzeigen → Senden an →
Desktop (Verknüpfung erstellen)**.
