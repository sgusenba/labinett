"""Webcam im Hintergrund lesen und Auto-Aufnahme auslösen."""

from __future__ import annotations

import sys
import threading
import time
from collections import deque
from collections.abc import Callable

import cv2
import numpy as np

from .erkennung import schnell_ecken


def _diagonale(ecken: np.ndarray) -> float:
    return float(max(np.linalg.norm(ecken[0] - ecken[2]), np.linalg.norm(ecken[1] - ecken[3])))


def ecken_ruhig(a: np.ndarray | None, b: np.ndarray | None, toleranz_rel: float) -> bool:
    """Keine Ecke hat sich um mehr als ``toleranz_rel`` × Rautendiagonale bewegt."""
    if a is None or b is None:
        return False
    tol = max(2.0, toleranz_rel * _diagonale(a))
    return float(np.max(np.linalg.norm(a - b, axis=1))) <= tol


def helligkeit(bild_bgr: np.ndarray) -> tuple[float, float]:
    """(Anteil ausgebrannter Pixel, 99-%-Helligkeit) auf einem kleinen Graubild."""
    g = cv2.cvtColor(bild_bgr, cv2.COLOR_BGR2GRAY) if bild_bgr.ndim == 3 else bild_bgr
    h, w = g.shape[:2]
    g = cv2.resize(g, (160, max(1, round(160 * h / w))), interpolation=cv2.INTER_AREA)
    return float(np.mean(g >= 250)), float(np.percentile(g, 99))


def naechste_belichtung(wert: float, dunkler: bool) -> float:
    """Einen Belichtungsschritt weiter.

    DirectShow (Windows) meldet log2-Sekunden (z. B. −6 = 1/64 s): ein Schritt = Faktor 2.
    V4L2 meldet die Zeit in 100 µs (positiv): ein Schritt = Faktor 0,7.
    """
    if wert <= 0:
        return max(-13.0, wert - 1) if dunkler else min(-1.0, wert + 1)
    return max(1.0, round(wert * 0.7)) if dunkler else min(10000.0, round(wert / 0.7))


def _grau_klein(bild_bgr: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(bild_bgr, cv2.COLOR_BGR2GRAY) if bild_bgr.ndim == 3 else bild_bgr
    return cv2.resize(g, (160, max(1, round(160 * g.shape[0] / g.shape[1]))), interpolation=cv2.INTER_AREA)


def karte_entfernt(
    referenz: np.ndarray, maske: np.ndarray, jetzt_bgr: np.ndarray, schwelle: int = 30, anteil: float = 0.6
) -> bool:
    """Sieht der Großteil der Stelle, an der die Karte lag, anders aus als bei der Aufnahme?

    Gezählt wird der Anteil veränderter Pixel, nicht der Mittelwert: eine Hand oder
    ein Lichtreflex verdeckt nur einen Teil, eine weggenommene Karte ändert fast alles.
    """
    jetzt = _grau_klein(jetzt_bgr)
    if jetzt.shape != referenz.shape or not maske.any():
        return True
    diff = cv2.absdiff(jetzt, referenz)
    return float(np.mean(diff[maske] > schwelle)) > anteil


class Kamera:
    """Liest Frames, erkennt die Raute live und meldet stabile Karten.

    Eine Auto-Aufnahme wird ausgelöst, wenn die Raute ``stabile_frames`` Frames
    lang ruhig liegt. Übergeben werden die letzten ``aufnahme_bilder`` ruhigen
    Frames, damit die Auswertung über mehrere Bilder abstimmen kann. Danach muss
    die Karte erst wieder aus dem Bild, bevor die nächste Auto-Aufnahme möglich ist.

    Belichtung und Weißabgleich bleiben standardmäßig automatisch: unter DirectShow
    meldet die Kamera während der Automatik meist nicht die tatsächliche, sondern
    eine alte gespeicherte Belichtung – diese festzuhalten ergab überbelichtete
    Bilder. Beim Öffnen und Beenden werden alle Automatiken wieder eingeschaltet,
    weil die Kamera „manuell“ sonst über das Programmende hinaus behält.

    ``sperren``: Nach einer Einlaufzeit werden Autofokus (und mit
    ``belichtung_festhalten`` auch Belichtung und
    Weißabgleich auf den aktuellen Werten festgehalten, damit das Bild nicht
    ständig nachgeregelt wird. Was die Kamera nicht unterstützt, wird übersprungen.
    """

    LEER_BIS_FREIGABE = 5  # so viele Frames ohne Karte, bis die Sperre fällt
    LEER_MIN_S = 0.4  # … und mindestens so lange (bei wenigen Bildern/s)
    # Belichtung nachregeln (nur wenn festgehalten): abdunkeln, wenn mehr als dieser
    # Anteil ausbrennt; aufhellen, wenn auf der Karte das hellste Prozent darunter liegt
    AUSGEBRANNT_MAX = 0.02
    ZU_DUNKEL_P99 = 130.0
    BELICHTUNG_PAUSE = 4  # Frames warten, bis ein neuer Wert im Bild wirkt
    # Einmessen: so viele Prüfungen in Folge überbelichtet (mit Karte), bis die Automatik
    # der Kamera durch einen eingemessenen festen Wert ersetzt wird
    EINMESSEN_NACH = 5
    EINMESSEN_MAX_SCHRITTE = 14
    EINLAUF_S = 3.0  # Sekunden Automatik, bevor die Werte festgehalten werden

    def __init__(
        self,
        index: int,
        breite: int,
        hoehe: int,
        stabile_frames: int,
        bei_aufnahme: Callable[[list[np.ndarray]], None],
        aufnahme_bilder: int = 3,
        toleranz_rel: float = 0.01,
        sperren: bool = True,
        fokus: int = -1,
        mjpg: bool = True,
        bei_entnahme: Callable[[], None] | None = None,
        belichtung_festhalten: bool = False,
        belichtung: float | None = None,
        belichtung_regeln: bool = True,
        belichtung_einmessen: bool = True,
        bei_belichtung: Callable[[float], None] | None = None,
    ) -> None:
        self.index = index
        self.breite = breite
        self.hoehe = hoehe
        self.stabile_frames = stabile_frames
        self.bei_aufnahme = bei_aufnahme
        self.aufnahme_bilder = max(1, aufnahme_bilder)
        self.toleranz_rel = toleranz_rel
        self.sperren = sperren
        self.fokus = fokus
        self.mjpg = mjpg
        self.auto_aktiv = True
        self.bei_entnahme = bei_entnahme
        self.belichtung_festhalten = belichtung_festhalten
        # Feste Belichtung vom Bediener (Regler), None = Automatik der Kamera
        self.belichtung_fest: float | None = belichtung
        self._belichtung_wunsch: tuple[float | None] | None = None  # im Lesethread anzuwenden
        self.belichtung_regeln = belichtung_regeln
        # Überbelichtung unter Kamera-Automatik: selbst einen festen Wert einmessen
        self.belichtung_einmessen = belichtung_einmessen
        self.bei_belichtung = bei_belichtung  # meldet den eingemessenen Wert (zum Speichern)
        self._einmessen: dict | None = None  # laufendes Einmessen: Wert, Richtung, Schritte
        self._einmess_wunsch = False
        self._einmess_versucht = belichtung is not None  # automatisch höchstens einmal je Lauf
        self._ueber = 0  # Prüfungen in Folge überbelichtet
        self.einmess_meldung: str | None = None
        self.belichtung: float | None = None  # aktueller Belichtungswert der Kamera
        self.ausgebrannt: float = 0.0  # Anteil ausgebrannter Pixel im letzten geprüften Bild
        self._bel_pause = 0
        self._bel_geht = True  # False, sobald die Kamera einen gesetzten Wert nicht übernimmt
        self.entnahmen = 0  # zählt erkannte Entnahmen (für die Oberfläche)
        self.fps: float | None = None  # gemessene Bilder pro Sekunde

        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_nr = 0  # zählt gelesene Frames, damit die Vorschau nur neue Bilder sendet
        self._vorschau: tuple[int, bytes] | None = None  # (Frame-Nr., JPEG) – einmal kodiert für alle Zuseher
        self._ruhig: deque[np.ndarray] = deque(maxlen=self.aufnahme_bilder)
        self._ecken: np.ndarray | None = None
        self._glatt: np.ndarray | None = None  # geglättete Ecken nur für die Anzeige
        self._stabil = 0
        self._gesperrt = False  # nach Aufnahme bis Karte entfernt
        self._leer = 0
        self._leer_seit: float | None = None
        # Aussehen der aufgenommenen Karte (kleines Graubild + Maske ihrer Fläche),
        # um die Entnahme am Bild statt nur am Verschwinden der Raute zu erkennen
        self._referenz: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        self._laeuft = False
        self._thread: threading.Thread | None = None
        self._dialog = False
        self._fokus_wunsch: int | None = None  # vom Bediener gewünschter Fokus, im Lesethread gesetzt
        self.fokus_aktuell: float | None = None
        self.autofokus = True
        self.fehler: str | None = None
        self.festgehalten: dict[str, bool] = {}

    # ------------------------------------------------------------ Steuerung

    def start(self) -> None:
        self._laeuft = True
        self._thread = threading.Thread(target=self._schleife, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._laeuft = False
        if self._thread:
            self._thread.join(timeout=2)

    def frame(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def frames(self) -> list[np.ndarray]:
        """Letzte ruhige Frames (für manuelle Aufnahme), sonst das aktuelle Bild."""
        with self._lock:
            if self._ecken is not None and len(self._ruhig) > 0:
                return [f.copy() for f in self._ruhig]
            return [] if self._frame is None else [self._frame.copy()]

    def treiber_dialog(self) -> None:
        """Einstellungsdialog des Kameratreibers öffnen (Windows/DirectShow)."""
        self._dialog = True

    def fokus_setzen(self, wert: int) -> None:
        """Fokus live ändern: ``wert`` ≥ 0 = fester Fokus, -1 = Autofokus neu scharfstellen lassen.

        Bei -1 läuft der Autofokus wieder, und – wenn ``sperren`` aktiv ist – wird der
        eingeregelte Wert nach der Einlaufzeit erneut festgehalten.
        """
        self._fokus_wunsch = int(wert)

    def belichtung_setzen(self, wert: float | None) -> None:
        """Feste Belichtung live setzen, ``None`` = Belichtungsautomatik der Kamera.

        Eine Bedienung beendet ein laufendes Einmessen; wer bewusst „Auto“ wählt, bekommt
        in diesem Lauf kein automatisches Einmessen mehr.
        """
        self._belichtung_wunsch = (wert,)
        self._einmess_versucht = True

    def einmessen(self) -> None:
        """Belichtung jetzt einmessen (Schaltfläche): abdunkeln, bis nichts mehr ausbrennt."""
        self._einmess_wunsch = True

    @staticmethod
    def belichtung_bereich() -> tuple[float, float]:
        """Regler-Bereich: DirectShow in log2-Sekunden (−8 ≈ 1/256 s), V4L2 in 100 µs."""
        return (-13.0, -1.0) if sys.platform.startswith("win") else (1.0, 2000.0)

    def _belichtung_anwenden(self, cap: cv2.VideoCapture, wert: float | None) -> None:
        win = sys.platform.startswith("win")
        try:
            if wert is None:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1 if win else 0.75)
            else:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0 if win else 0.25)
                cap.set(cv2.CAP_PROP_EXPOSURE, wert)
            self.belichtung = float(cap.get(cv2.CAP_PROP_EXPOSURE))
        except cv2.error:
            pass
        self.belichtung_fest = wert

    def status(self) -> dict:
        with self._lock:
            return {
                "kamera_ok": self._frame is not None and self.fehler is None,
                "fehler": self.fehler,
                "karte_erkannt": self._ecken is not None,
                "stabil": min(1.0, self._stabil / max(1, self.stabile_frames)),
                "wartet_auf_neue_karte": self._gesperrt,
                "entnahmen": self.entnahmen,
                "belichtung": self.belichtung,
                "belichtung_fest": self.belichtung_fest,
                "belichtung_bereich": self.belichtung_bereich(),
                "ausgebrannt": round(self.ausgebrannt, 3),
                "einmessen": self._einmessen is not None,
                "einmess_meldung": self.einmess_meldung,
                "auto_aktiv": self.auto_aktiv,
                "festgehalten": dict(self.festgehalten),
                "fokus": self.fokus_aktuell,
                "autofokus": self.autofokus,
                "fps": None if self.fps is None else round(self.fps, 1),
            }

    def vorschau(self, nach: int = -1) -> tuple[int, bytes] | None:
        """Vorschau-JPEG mit Frame-Nummer, nur wenn ein neueres Bild als ``nach`` vorliegt."""
        with self._lock:
            nr = self._frame_nr
            zwischen = self._vorschau
        if nr <= nach:
            return None
        if zwischen is not None and zwischen[0] == nr:
            return zwischen
        jpg = self.vorschau_jpeg()
        if jpg is None:
            return None
        with self._lock:
            self._vorschau = (nr, jpg)
        return nr, jpg

    def vorschau_jpeg(self) -> bytes | None:
        with self._lock:
            if self._frame is None:
                return None
            bild = self._frame.copy()
            ecken = None if self._glatt is None else self._glatt.copy()
            stabil = self._stabil
            gesperrt = self._gesperrt
        if ecken is not None:
            farbe = (0, 200, 0) if gesperrt or stabil >= self.stabile_frames else (0, 200, 255)
            cv2.polylines(bild, [np.round(ecken).astype(np.int32)], True, farbe, 4, cv2.LINE_AA)
        h, w = bild.shape[:2]
        f = min(1.0, 800 / w)
        if f < 1:
            bild = cv2.resize(bild, None, fx=f, fy=f)
        ok, buf = cv2.imencode(".jpg", bild, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else None

    # ------------------------------------------------------------ intern

    def _oeffnen(self) -> cv2.VideoCapture:
        api = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.index, api)
        try:
            # MJPG vor der Auflösung setzen: unkomprimiert schaffen USB-2-Webcams
            # bei 1920 × 1080 oft nur 5 Bilder/s, mit MJPG 30.
            if self.mjpg:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.breite)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.hoehe)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # kein Rückstau alter Bilder
        except cv2.error:
            pass
        self._automatik_an(cap, fokus=self.fokus < 0)
        if self.belichtung_fest is not None:
            self._belichtung_anwenden(cap, self.belichtung_fest)
        return cap

    @staticmethod
    def _automatik_an(cap: cv2.VideoCapture, fokus: bool = True) -> None:
        """Belichtung, Weißabgleich (und Fokus) der Kamera wieder automatisch regeln lassen.

        Die Kamera speichert diese Einstellungen im Gerät; ohne Rücksetzen bliebe sie nach
        einem Programmlauf auf festen Werten stehen.
        """
        auto = 1 if sys.platform.startswith("win") else 0.75  # DirectShow: 1 = Auto; V4L2: 0,75 = Auto
        werte = [(cv2.CAP_PROP_AUTO_EXPOSURE, auto), (cv2.CAP_PROP_AUTO_WB, 1)]
        if fokus:
            werte.append((cv2.CAP_PROP_AUTOFOCUS, 1))
        for prop, wert in werte:
            try:
                cap.set(prop, wert)
            except cv2.error:
                pass

    def _festhalten(self, cap: cv2.VideoCapture) -> None:
        """Automatiken abschalten und die gerade eingeregelten Werte behalten."""
        erg: dict[str, bool] = {}

        def setze(prop: int, wert: float) -> bool:
            try:
                return bool(cap.set(prop, wert))
            except cv2.error:
                return False

        fokus = self.fokus if self.fokus >= 0 else cap.get(cv2.CAP_PROP_FOCUS)
        erg["fokus"] = setze(cv2.CAP_PROP_AUTOFOCUS, 0) | setze(cv2.CAP_PROP_FOCUS, fokus)
        self.autofokus = not erg["fokus"]
        if not self.belichtung_festhalten or self.belichtung_fest is not None:
            self.festgehalten = erg
            return
        belichtung = cap.get(cv2.CAP_PROP_EXPOSURE)
        # DirectShow schaltet beim Setzen eines Werts auf manuell, V4L2 braucht AUTO_EXPOSURE=1/0.25
        manuell = 0.25 if not sys.platform.startswith("win") else 0
        erg["belichtung"] = setze(cv2.CAP_PROP_AUTO_EXPOSURE, manuell) | setze(cv2.CAP_PROP_EXPOSURE, belichtung)
        wb = cap.get(cv2.CAP_PROP_WB_TEMPERATURE)
        erg["weissabgleich"] = setze(cv2.CAP_PROP_AUTO_WB, 0) | (wb > 0 and setze(cv2.CAP_PROP_WB_TEMPERATURE, wb))
        self.festgehalten = erg

    def _fokus_anwenden(self, cap: cv2.VideoCapture, wert: int) -> bool:
        """Gewünschten Fokus setzen; True = Autofokus läuft wieder (Einlauf neu starten)."""
        try:
            if wert < 0:
                self.fokus = -1
                self.autofokus = True
                cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
                return True
            self.fokus = wert
            self.autofokus = False
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            cap.set(cv2.CAP_PROP_FOCUS, wert)
        except cv2.error:
            pass
        return False

    def _fokus_lesen(self, cap: cv2.VideoCapture) -> None:
        try:
            self.fokus_aktuell = float(cap.get(cv2.CAP_PROP_FOCUS))
        except cv2.error:
            self.fokus_aktuell = None

    def _belichtung_pruefen(self, cap: cv2.VideoCapture, frame: np.ndarray, karte_da: bool) -> None:
        """Festgehaltene Belichtung nachführen, z. B. wenn das Ringlicht eingeschaltet wird."""
        if self._bel_pause > 0:
            self._bel_pause -= 1
            return
        aus, p99 = helligkeit(frame)
        self.ausgebrannt = aus
        if not (self.belichtung_regeln and self._bel_geht and self.festgehalten.get("belichtung")):
            return
        dunkler = aus > self.AUSGEBRANNT_MAX
        heller = karte_da and p99 < self.ZU_DUNKEL_P99  # ohne Karte nicht aufhellen (dunkle Unterlage)
        if not (dunkler or heller):
            return
        try:
            alt = float(cap.get(cv2.CAP_PROP_EXPOSURE))
            neu = naechste_belichtung(alt, dunkler)
            if neu == alt:
                return
            cap.set(cv2.CAP_PROP_EXPOSURE, neu)
            gelesen = float(cap.get(cv2.CAP_PROP_EXPOSURE))
        except cv2.error:
            self._bel_geht = False
            return
        if gelesen == alt:  # Kamera übernimmt keine Belichtungswerte
            self._bel_geht = False
            return
        self.belichtung = gelesen
        self._bel_pause = self.BELICHTUNG_PAUSE

    def _einmessen_starten(self, cap: cv2.VideoCapture) -> None:
        """Auf manuelle Belichtung umschalten, Startwert = aktueller Wert der Kamera."""
        lo, hi = self.belichtung_bereich()
        try:
            wert = float(cap.get(cv2.CAP_PROP_EXPOSURE))
        except cv2.error:
            wert = float("nan")
        if not lo <= wert <= hi:  # Automatik meldet oft Unsinn: in der Mitte beginnen
            wert = round((lo + hi) / 2)
        self._belichtung_anwenden(cap, wert)
        self._einmessen = {"wert": wert, "richtung": 0, "schritte": 0}
        self._einmess_versucht = True
        self._bel_pause = self.BELICHTUNG_PAUSE
        self.einmess_meldung = "Belichtung wird eingemessen …"

    def _einmessen_ende(self, wert: float | None, meldung: str) -> None:
        self._einmessen = None
        self.einmess_meldung = meldung
        if wert is not None and self.bei_belichtung:
            try:
                self.bei_belichtung(wert)
            except Exception as e:  # Speichern darf die Kamera nicht stoppen
                self.fehler = f"Belichtung speichern: {e}"

    def _einmessen_schritt(self, cap: cv2.VideoCapture, aus: float, p99: float, karte_da: bool) -> None:
        """Ein Schritt: dunkler, solange etwas ausbrennt; heller, wenn die Karte zu dunkel ist.

        Wechselt die Richtung, liegt der passende Wert dazwischen – dann wird der
        dunklere genommen (lieber etwas dunkel als ausgebrannte Linien).
        """
        m = self._einmessen
        alt = m["wert"]
        dunkler = aus > self.AUSGEBRANNT_MAX
        heller = not dunkler and karte_da and p99 < self.ZU_DUNKEL_P99
        if not (dunkler or heller):
            self._einmessen_ende(alt, f"Belichtung eingemessen: {alt:g}")
            return
        if heller and m["richtung"] < 0:  # vorher zu hell, jetzt zu dunkel: dabei bleiben
            self._einmessen_ende(alt, f"Belichtung eingemessen: {alt:g}")
            return
        if m["schritte"] >= self.EINMESSEN_MAX_SCHRITTE:
            self._einmessen_ende(alt, f"Belichtung eingemessen: {alt:g} (Grenze erreicht)")
            return
        neu = naechste_belichtung(alt, dunkler)
        lo, hi = self.belichtung_bereich()
        neu = min(hi, max(lo, neu))
        if neu == alt:
            self._einmessen_ende(alt, f"Belichtung {alt:g} – Grenze der Kamera erreicht, Licht schwächer stellen")
            return
        try:
            cap.set(cv2.CAP_PROP_EXPOSURE, neu)
            gelesen = float(cap.get(cv2.CAP_PROP_EXPOSURE))
        except cv2.error:
            gelesen = alt
        if gelesen == alt:
            self._belichtung_anwenden(cap, None)
            self._einmessen_ende(None, "Kamera übernimmt keine Belichtungswerte – bitte im Kamera-Treiber einstellen")
            return
        self.belichtung = gelesen
        self.belichtung_fest = gelesen
        m.update(wert=gelesen, richtung=-1 if dunkler else 1, schritte=m["schritte"] + 1)
        self._bel_pause = self.BELICHTUNG_PAUSE

    def _einmessen_pruefen(self, cap: cv2.VideoCapture, frame: np.ndarray, karte_da: bool) -> bool:
        """Einmessen anstoßen bzw. fortsetzen. True = Einmessen läuft (Nachregeln ruht)."""
        if self._einmess_wunsch:
            self._einmess_wunsch = False
            self._einmessen_starten(cap)
            return True
        if self._einmessen is not None:
            if self._bel_pause > 0:
                self._bel_pause -= 1
                return True
            aus, p99 = helligkeit(frame)
            self.ausgebrannt = aus
            self._einmessen_schritt(cap, aus, p99, karte_da)
            return True
        # automatisch: nur unter Kamera-Automatik, nur mit Karte, nur einmal je Lauf
        if (
            not self.belichtung_einmessen
            or self._einmess_versucht
            or self.belichtung_fest is not None
            or self.festgehalten.get("belichtung")
        ):
            return False
        self._ueber = self._ueber + 1 if karte_da and self.ausgebrannt > self.AUSGEBRANNT_MAX else 0
        if self._ueber < self.EINMESSEN_NACH:
            return False
        self._ueber = 0
        self._einmessen_starten(cap)
        return True

    def _merke_karte(self, frame: np.ndarray, ecken: np.ndarray) -> None:
        g = _grau_klein(frame)
        f = g.shape[1] / frame.shape[1]
        maske = np.zeros(g.shape, np.uint8)
        cv2.fillConvexPoly(maske, np.round(ecken * f).astype(np.int32), 1)
        self._referenz = (g, maske.astype(bool), ecken.copy())

    def _entnommen(self, frame: np.ndarray, ecken: np.ndarray | None) -> bool:
        """Karte gilt als weg, wenn die Raute fehlt oder woanders liegt UND die Stelle anders aussieht."""
        if self._referenz is None:
            return ecken is None
        ref, maske, ref_ecken = self._referenz
        if ecken is not None and ecken_ruhig(ecken, ref_ecken, 0.05):
            return False  # liegt noch da
        return karte_entfernt(ref, maske, frame)

    def _glaetten(self, ecken: np.ndarray | None) -> None:
        if ecken is None:
            self._glatt = None
        elif self._glatt is None or not ecken_ruhig(ecken, self._glatt, 0.05):
            self._glatt = ecken.astype(np.float64)
        else:
            self._glatt = self._glatt + 0.4 * (ecken - self._glatt)

    def _schleife(self) -> None:
        cap = self._oeffnen()
        letzte = None
        start = time.monotonic()
        festgehalten = not self.sperren
        n = 0
        letzt_t: float | None = None
        while self._laeuft:
            if not cap.isOpened():
                self.fehler = f"Kamera {self.index} lässt sich nicht öffnen"
                time.sleep(2)
                cap.release()
                cap = self._oeffnen()
                start = time.monotonic()
                festgehalten = not self.sperren
                continue
            if self._dialog:
                self._dialog = False
                try:
                    cap.set(cv2.CAP_PROP_SETTINGS, 1)
                except cv2.error:
                    pass
            if self._belichtung_wunsch is not None:
                (bel,), self._belichtung_wunsch = self._belichtung_wunsch, None
                if self._einmessen is not None:  # Bediener hat übernommen
                    self._einmessen = None
                    self.einmess_meldung = None
                self._belichtung_anwenden(cap, bel)
            if self._fokus_wunsch is not None:
                wunsch, self._fokus_wunsch = self._fokus_wunsch, None
                if self._fokus_anwenden(cap, wunsch):
                    start = time.monotonic()
                    festgehalten = not self.sperren
                self._fokus_lesen(cap)
            n += 1
            if n % 15 == 0:  # Autofokus wandert, Anzeige gelegentlich nachziehen
                self._fokus_lesen(cap)
            ok, frame = cap.read()
            if not ok:
                self.fehler = "Kein Bild von der Kamera"
                time.sleep(0.5)
                continue
            self.fehler = None
            jetzt = time.monotonic()
            if letzt_t is not None and jetzt > letzt_t:
                f = 1.0 / (jetzt - letzt_t)
                self.fps = f if self.fps is None else self.fps + 0.1 * (f - self.fps)
            letzt_t = jetzt
            if not festgehalten and time.monotonic() - start >= self.EINLAUF_S:
                try:
                    self._festhalten(cap)
                except Exception:  # Kamera ohne diese Eigenschaften: Automatik bleibt
                    self.festgehalten = {}
                festgehalten = True
                self._fokus_lesen(cap)
            ecken = schnell_ecken(frame)
            if festgehalten and n % 3 == 0:
                if not self._einmessen_pruefen(cap, frame, ecken is not None):
                    self._belichtung_pruefen(cap, frame, ecken is not None)
            fertig: list[np.ndarray] | None = None
            entnommen = False
            with self._lock:
                self._frame = frame
                self._frame_nr += 1
                self._ecken = ecken
                self._glaetten(ecken)
                if self._gesperrt:
                    # nach einer Aufnahme: erst weiter, wenn die Karte wirklich weg ist
                    if self._entnommen(frame, ecken):
                        self._leer += 1
                        self._leer_seit = self._leer_seit or jetzt
                        if self._leer >= self.LEER_BIS_FREIGABE and jetzt - self._leer_seit >= self.LEER_MIN_S:
                            self._gesperrt = False
                            self._referenz = None
                            self.entnahmen += 1
                            entnommen = True
                    else:
                        self._leer = 0
                        self._leer_seit = None
                if ecken is None:
                    self._stabil = 0
                    self._ruhig.clear()
                else:
                    if not self._gesperrt:
                        self._leer = 0
                        self._leer_seit = None
                    if ecken_ruhig(ecken, letzte, self.toleranz_rel):
                        self._stabil += 1
                    else:
                        self._stabil = 0
                        self._ruhig.clear()
                    self._ruhig.append(frame)
                    if self.auto_aktiv and not self._gesperrt and self._stabil >= self.stabile_frames:
                        self._gesperrt = True
                        self._leer = 0
                        self._leer_seit = None
                        self._merke_karte(frame, ecken)
                        fertig = [f.copy() for f in self._ruhig]
            letzte = ecken
            if entnommen and self.bei_entnahme:
                try:
                    self.bei_entnahme()
                except Exception as e:
                    self.fehler = f"Entnahme: {e}"
            if fertig:
                try:
                    self.bei_aufnahme(fertig)
                except Exception as e:  # Auswertung darf die Kamera nicht stoppen
                    self.fehler = f"Auswertung fehlgeschlagen: {e}"
        self._automatik_an(cap)  # Kamera nicht verstellt zurücklassen
        cap.release()
