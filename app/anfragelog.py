"""Anonymes Anfrage-Log für das Admin-Dashboard (DSGVO-orientiert).

Gespeichert wird nur, was der Auftraggeber zur Auswertung braucht: Frage,
Antwort, Zeitpunkt, Thema und auf welcher DHI-Seite das Widget benutzt wurde.
Bewusst NICHT gespeichert: IP-Adresse, User-Agent, Cookies oder andere
Geräte-Kennungen. Fragen eines Gesprächs gruppiert eine Zufalls-ID, die das
Widget pro Seitenaufruf im Arbeitsspeicher erzeugt (kein Cookie, kein
localStorage) und die sich keiner Person zuordnen lässt.

Kontaktdaten, die Besucher trotzdem eintippen (E-Mail, Telefon, IBAN), werden
vor dem Speichern geschwärzt. Einträge älter als ANFRAGEN_AUFBEWAHRUNG_TAGE
werden bei jedem Schreiben gelöscht.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import ANFRAGEN_AUFBEWAHRUNG_TAGE, CONTACT, DATA_DIR, TIMEZONE

DB = DATA_DIR / "anfragen.db"
_lock = threading.Lock()

# shortcut: Namen/Adressen im Freitext werden nicht erkannt, nur maschinenlesbare
# Kontaktdaten — reicht, solange das Widget um keine Personendaten bittet.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b")
# Telefonnummern beginnen mit 0 oder + (+49 151 123 45 67, 06021/920-8003).
# Punkte zählen bewusst nicht als Trenner: sonst träfe es Daten wie 11.01.2027.
_TELEFON = re.compile(r"(?<!\w)(?:\+|0)\d[\d \t/()-]{4,}\d")
# Die eigenen DHI-Nummern stehen in fast jeder Antwort und bleiben lesbar
_EIGENE = {re.sub(r"\D", "", CONTACT[k]) for k in ("telefon", "whatsapp")}

_THEMEN = [
    ("Termine", r"termin|wann|datum|nächste|naechste|kalender|übungstag|uebungstag"),
    ("Preise & Zahlung", r"preis|kost|€|euro|\braten?\b|rabatt|skonto|zahlung|bezahl|"
                         r"günstig|teuer|förder"),
    ("Standorte & Format", r"\bwo\b|\borte?\b|standort|stadt|online|hybrid|präsenz|"
                           r"praesenz|dhi ?[123]|hamburg|münchen|stuttgart|leipzig|"
                           r"aschaffenburg|oberstaufen|berlin"),
    ("Ausbildung & Inhalte", r"ausbildung|stufe|seminar|kurs|lern|inhalt|zertifi|prüfung|"
                             r"hypnotiseur"),
    ("Beratung & Kontakt", r"berat|kontakt|anruf|telefon|whatsapp|e-?mail|sprechen"),
    ("Hypnose-Sitzung", r"sitzung|praxis|behandl|therap|rauch|abnehm|angst|schlaf"),
]


def _telefon(m: re.Match) -> str:
    ziffern = re.sub(r"\D", "", m.group(0))
    return m.group(0) if len(ziffern) < 6 or ziffern in _EIGENE else "[Telefon]"


def schwaerzen(text: str) -> str:
    """Ersetzt E-Mail-Adressen, IBANs und Telefonnummern durch Platzhalter."""
    text = _EMAIL.sub("[E-Mail]", text)
    text = _IBAN.sub("[IBAN]", text)
    return _TELEFON.sub(_telefon, text)


def thema(frage: str) -> str:
    f = frage.lower()
    for name, muster in _THEMEN:
        if re.search(muster, f):
            return name
    return "Sonstiges"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE IF NOT EXISTS anfragen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,          -- UTC, ISO 8601
            tag TEXT NOT NULL,         -- lokales Datum (TIMEZONE) für Tagesstatistik
            gespraech TEXT NOT NULL,   -- Zufalls-ID aus dem Widget, nicht personenbezogen
            seite TEXT NOT NULL,       -- Hostname der DHI-Seite (Origin), ohne Pfad
            thema TEXT NOT NULL,
            frage TEXT NOT NULL,
            antwort TEXT NOT NULL,
            art TEXT NOT NULL          -- llm | termine | mock | fehler
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS anfragen_ts ON anfragen(ts)")
    return c


def speichern(gespraech: str, seite: str, frage: str, antwort: str, art: str) -> None:
    jetzt = datetime.now(timezone.utc)
    grenze = (jetzt - timedelta(days=ANFRAGEN_AUFBEWAHRUNG_TAGE)).isoformat(timespec="seconds")
    frage = schwaerzen(frage)
    with _lock, closing(_conn()) as c, c:
        c.execute(
            "INSERT INTO anfragen (ts, tag, gespraech, seite, thema, frage, antwort, art) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                jetzt.isoformat(timespec="seconds"),
                jetzt.astimezone(ZoneInfo(TIMEZONE)).date().isoformat(),
                re.sub(r"[^\w-]", "", gespraech)[:40] or "unbekannt",
                seite[:100] or "unbekannt",
                thema(frage),
                frage[:1500],
                schwaerzen(antwort)[:4000],
                art,
            ),
        )
        c.execute("DELETE FROM anfragen WHERE ts < ?", (grenze,))


def auswertung(tage: int = 30, suche: str = "", limit: int = 500) -> dict:
    """Kennzahlen und die neuesten Anfragen der letzten `tage` Tage."""
    seit = (datetime.now(timezone.utc) - timedelta(days=tage)).isoformat(timespec="seconds")
    wo, args = "ts >= ?", [seit]
    if suche:
        wo += " AND (frage LIKE ? OR antwort LIKE ?)"
        args += [f"%{suche}%"] * 2
    with _lock, closing(_conn()) as c:
        def gruppe(spalte: str) -> dict:
            return {r[0]: r[1] for r in c.execute(
                f"SELECT {spalte}, COUNT(*) FROM anfragen WHERE {wo} "
                f"GROUP BY {spalte} ORDER BY COUNT(*) DESC", args)}

        gesamt, gespraeche = c.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT gespraech) FROM anfragen WHERE {wo}", args
        ).fetchone()
        return {
            "zeitraum_tage": tage,
            "aufbewahrung_tage": ANFRAGEN_AUFBEWAHRUNG_TAGE,
            "gesamt": gesamt,
            "gespraeche": gespraeche,
            "pro_tag": dict(sorted(gruppe("tag").items())),
            "themen": gruppe("thema"),
            "seiten": gruppe("seite"),
            "arten": gruppe("art"),
            "anfragen": [dict(r) for r in c.execute(
                f"SELECT id, ts, gespraech, seite, thema, frage, antwort, art FROM anfragen "
                f"WHERE {wo} ORDER BY id DESC LIMIT ?", [*args, limit])],
        }


def loeschen(eintrag_id: int) -> bool:
    with _lock, closing(_conn()) as c, c:
        return c.execute("DELETE FROM anfragen WHERE id = ?", (eintrag_id,)).rowcount > 0
