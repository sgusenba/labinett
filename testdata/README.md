# Testdaten Nikolo-Scheibe

Fotos echter Nikolo-Scheiben (Schützenverein Bad Zell), Handy-Aufnahmen auf dunklem Untergrund.
Gesamtwert = handschriftlich auf der Karte eingetragenes Ergebnis (Referenz für die Auswertung).

| Datei | Datum (Karte) | Gesamt (handschriftlich) | Hinweise |
|---|---|---|---|
| nikolo_01.jpg | 2.12.23 | 104 | zweite Karte unten angeschnitten, Treffer überlappend, ein Schuss am unteren Rand |
| nikolo_02.jpg | 3.12.22 | 138 | Karte oben angeschnitten im Bild |
| nikolo_03.jpg | 12.22 | 162 | Wasserfleck, Treffer auf Linien |
| nikolo_04.jpg | 3.12.2022 | 147 | ein Schuss außerhalb an der Spitze |
| nikolo_05.jpg | 2.12.23 | 136 | überlappende Treffer, Notizen links unten |
| nikolo_06.jpg | 2.12.24 | 71 | Karte schräg/teilweise angeschnitten |
| nikolo_07.jpg | 2.12.24 | 98 | Notizen links unten |

## Webcam-Aufnahmen (1920 × 1080, Aufbau wie im Betrieb)

| Datei | Karte | Gesamt (handschriftlich) | Erkennung | Hinweise |
|---|---|---|---|---|
| WIN_20261118_20_17_53_Pro.jpg | = nikolo_02 | 138 (43, 28, 53, 13, 1) | 105 | zwei Grenzfälle an Linie/Ecke, beide als unsicher markiert |
| WIN_20261118_20_18_05_Pro.jpg | = nikolo_04 | 147 | 147 | |
| WIN_20261118_20_18_20_Pro.jpg | = nikolo_01 | 104 | 104 | |
| WIN_20261118_20_18_29_Pro.jpg | = nikolo_05 | 136 (53, 15+13+7, 13, 13, 22) | 154 | Eckschuss: Hand ohne 18, Erkennung mit 18 (0,1 mm), als unsicher markiert |
| WIN_20261118_20_18_41_Pro.jpg | = nikolo_07 | Box 98, Nebenrechnung 131 | 131 | Box-Summe hat den Schuss 15+18 = 33 vergessen |
| WIN_20261118_20_18_51_Pro.jpg | neu | 59 | 59 | |
| WIN_20261118_20_19_03_Pro.jpg | neu | – | 94 | Feldwerte am Foto nachgezählt; Schuss 5+10+16 knapp, unsicher |
| WIN_20261118_20_19_22_Pro.jpg | neu | 85 | 83 | Felder 17+19, 17, 1, 1+14, 14 = 83; kein Grenzfall erkennbar → Handsumme bitte prüfen |

Messungen auf diesen Fotos (Grundlage für die Parameter):

- Linienstärke ≈ 0,45 mm (Einstellung `linienbreite_mm` 0,4 passt).
- Lochmittelpunkt Webcam vs. Handy auf derselben Karte: max. 0,46 mm Abweichung.
- Unter Drehung, 720p/540p, Unschärfe, Helligkeit, JPEG, Rauschen, Perspektive:
  einzelne Löcher 99 % < 0,35 mm, aus überlappenden Flecken aufgeteilte Löcher bis 0,8 mm.
  Deshalb gilt für aufgeteilte Löcher die doppelte Unsicherheits-Toleranz.
- 188 von 195 gestörten Auswertungen ergeben exakt die Referenz; alle Abweichungen
  betreffen Schüsse, die ohnehin als unsicher markiert sind.
