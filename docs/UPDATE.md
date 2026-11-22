# Auto-Update

## Versionen

- Jeder Push auf `main` baut die `labinett.exe` und veröffentlicht sie als
  GitHub-Release **`v<MAJOR>.<MINOR>.<BUILD>`** (Workflow `.github/workflows/ci.yml`).
- `MAJOR.MINOR` steht in der Datei [`VERSION`](../VERSION). `BUILD` zählt die
  Action selbst hoch: höchster vorhandener Tag `vMAJOR.MINOR.*` + 1. Wird
  `VERSION` geändert (z. B. auf `0.2`), beginnt `BUILD` wieder bei 1.
- Die Action schreibt die Version vor dem Build nach `labinett/_version.py`
  (nicht eingecheckt). Die Oberfläche zeigt sie oben rechts.
- Pull-Request- und Test-Builds bekommen eine `.devN`-Version und
  aktualisieren sich nie selbst; ebenso `python -m labinett`.
- Zu jedem Release gehört `labinett.exe.sha256`, gegen die der Updater prüft.
- Läufe sind über `concurrency` serialisiert, damit nie zwei Builds dieselbe
  Nummer vergeben.

## Ablauf beim Start der .exe

1. **Bereitliegendes Update einspielen** (ohne Netz, < 1 s):
   Liegt `labinett.exe.neu` neben der .exe, wird die laufende Datei in
   `labinett.exe.alt` umbenannt (Windows erlaubt das bei laufenden Programmen),
   `.neu` an ihre Stelle geschoben, die neue Version gestartet und die alte
   beendet. Beim nächsten Start wird `.alt` gelöscht.
2. **Programm startet normal** – Kamera, Browser, alles wie bisher.
3. **Im Hintergrund** fragt ein Thread
   `api.github.com/repos/sgusenba/labinett/releases/latest` (Timeout 10 s).
   - kein Netz / Fehler / Rate-Limit → nichts passiert, kein Hinweis, keine
     Verzögerung;
   - gleiche oder ältere Version → fertig;
   - neuere Version → `labinett.exe` nach `labinett.exe.download` laden,
     SHA-256 prüfen, erst dann in `labinett.exe.neu` umbenennen. Die
     Kopfzeile zeigt „Update x.y.z bereit – wird beim nächsten Start installiert“.

Ein Update wird also nie mitten im Wettkampf eingespielt, sondern erst beim
nächsten Programmstart. Abgebrochene Downloads bleiben `.download` und werden
verworfen; eine falsche Prüfsumme verwirft das Update.

## Abschalten

`"auto_update": false` in `labinett.json` (oder in der Oberfläche unter
Einstellungen „Beim Start nach Updates suchen“). Für einen einzelnen Start:
Umgebungsvariable `LABINETT_KEIN_UPDATE=1` verhindert auch das Einspielen.

## Zurück auf eine ältere Version

Programm beenden, gewünschte `labinett.exe` von der Releases-Seite laden und
ersetzen, `auto_update` auf `false` stellen – sonst holt sich das Programm
die neueste Version beim nächsten Start wieder.
