"""Deterministische Terminantworten (QS-Befund 8, v0.2.3).

Reine Terminlistenfragen („Welche Übungstage gibt es in Stuttgart?") werden
nicht mehr vom LLM beantwortet, sondern direkt per strukturiertem Filter über
data/termine.json: chronologisch sortiert, frühester passender Termin garantiert
zuerst, mit Buchungslink. Hintergrund: Das Modell ließ bei Standort-Listenfragen
selten den frühesten Termin aus (Auslassungs-, kein Halluzinationsproblem).

Konservatives Gating — deterministisch wird NUR geantwortet, wenn alles zutrifft:
  1. Die Frage enthält ein Terminsignal (wann/Termin/startet/…) oder eine
     Listenfrage nach einer konkreten Kursart („Welche Übungstage …?").
  2. Mindestens ein bekannter Filter wurde erkannt: Standort aus termine.json,
     Stufe (1+2 / 3) oder Kursart (Übungstage / Vollpräsenz / Live-Online).
  3. Kein Gegen-Signal: Preise, Buchung/Verfügbarkeit, Inhalte, Vergleiche,
     Uhrzeit-/Wochentagsfragen — und kein unbekannter Ort („… in Frankfurt?").
  4. Der Filter liefert mindestens einen zukünftigen Termin.

In allen anderen Fällen gibt try_answer() None zurück und der bisherige
LLM-Pfad übernimmt (der z.B. beim Wunsch-Standort Frankfurt die beste
Alternative anbieten kann — das kann ein starres Template nicht).

Abschaltbar per .env: DETERMINISTIC_TERMINE=0 (Standard: an).
"""
from __future__ import annotations

import re
from datetime import date, datetime

from . import retrieval

SEMINARKALENDER_URL = "https://deutsches-hypnoseinstitut.de/seminarkalender.html"

# Kurzlabels für die Antwortzeilen (bewusst eigenständig von llm.KIND_LABEL,
# um zirkuläre Importe zu vermeiden).
_KIND_LABEL = {
    "presence": "Vollpräsenz (DHI 1.0)",
    "hybrid": "Live-Online-Theorie (DHI 2.0)",
    "practice": "Präsenz-Übungstage (DHI 2.0)",
}

_MAX_LISTE = 3  # Regel 2 des System-Prompts: höchstens 3 Aufzählungspunkte


# ── 1 · Frage verstehen (konservativ) ────────────────────────────────────────

# Starke Terminsignale: eindeutig eine Frage nach dem „Wann".
_TERMIN_SIGNAL = re.compile(
    r"\b(termine?s?n?|wann|datum|daten|startet|starten|starttermin\w*|start|"
    r"beginnt|beginnen|beginn|stattfinde\w*|findet|finden|kalender|angeboten)\b"
)

# Listensignale: reichen nur zusammen mit einer EXPLIZITEN Kursart
# („Welche Übungstage gibt es …?" ist eine Terminfrage, „Welche Inhalte …?" nicht).
_LISTEN_SIGNAL = re.compile(
    r"\b(welche[rns]?|nächste[rns]?|naechste[rns]?|gibt es|gibts|habt ihr|haben sie|kommende[rns]?)\b"
)

# Gegen-Signale → immer LLM-Pfad (dort gibt es PREISDATEN, Beratung, Kontext).
_BLOCKER = re.compile(
    r"preis|kost|teuer|€|euro|rate|skonto|rabatt|geb[üu]hr|bezahl|zahlung|anzahlung|invest|finanz|"
    r"buch|anmeld|reservier|pl[äa]tze|platz\b|frei\b|verf[üu]gbar|storn|warteliste|"
    r"inhalt|lern|lehr|curricul|zertifi|pr[üu]fung|abschluss|voraussetzung|vorkenntnis|"
    r"unterschied|vergleich|besser|empfehl|erfahrung|meinung|lohnt|"
    r"uhrzeit|\buhr\b|wochenend|feiertag|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|"
    r"wie lange|wie oft|wie viele|dauer|"
    r"hotel|[üu]bernacht|anfahrt|park|unterlagen|skript|absag|verschob|krank|erstatt"
)

# Wörter, die nach „in/bei/nach/aus/um" stehen dürfen, ohne ein Ort zu sein.
_KEIN_ORT = {
    "der", "die", "das", "den", "dem", "des", "einer", "einem", "einen", "eine",
    "diesem", "dieser", "dieses", "welchem", "welcher", "welchen", "meiner",
    "meinem", "ihrer", "ihrem", "seiner", "unserer", "eurer", "euch", "ihnen",
    "uns", "mir", "dir", "sich", "hause", "etwa", "ca", "rund", "kürze",
    "kuerze", "zukunft", "ruhe", "ordnung", "anspruch", "frage", "präsenz",
    "praesenz", "raten", "deutschland", "nähe", "naehe", "meiner", "anschluss",
}

# Präposition + folgendes Wort — zum Erkennen unbekannter Wunsch-Orte
# („Gibt es Termine in Frankfurt?" → gehört zum LLM, das Alternativen anbietet).
_ORT_KANDIDAT = re.compile(r"\b(?:in|bei|nach|aus|um)\s+([a-zäöüß][a-zäöüß.\-]+)")

_STAGE_12 = re.compile(r"stufe\W*1(\W*(\+|und|&|bis)?\W*2)?\b|stufe\W*2\b|grundausbildung")
_STAGE_3 = re.compile(r"stufe\W*3\b|masterclass|expertenausbildung|experten-ausbildung")

_KIND_PATTERNS = [
    ("practice", re.compile(r"[üu]bungs\W?tag|praxis\W?tag|[üu]bungstermine?")),
    ("presence", re.compile(r"voll\W?pr[äa]senz|dhi\W*1(\.0)?\b")),
    ("hybrid", re.compile(r"hybrid|live\W?online|\bonline\b|dhi\W*2(\.0)?\b")),
]

# „Kurs/Ausbildung/Seminar startet …" meint den Ausbildungsstart — reine
# Übungstage sind Praxisbausteine, kein Kursstart. (Greift nur ohne Ortsfilter,
# damit „Ausbildung in Leipzig" weiterhin die dortigen Übungstage findet.)
_KURS_WORT = re.compile(r"\bkurs\w*|ausbildung\w*|seminar\w*")


def _parse(message: str, known_locations: dict[str, str]) -> dict | None:
    """Extrahiert Filter aus der Frage — oder None, wenn die Frage nicht
    eindeutig eine reine Terminlistenfrage ist."""
    q = " ".join(message.lower().split())
    if not q or len(q) > 300:
        return None
    if _BLOCKER.search(q):
        return None

    # Kursart
    kinds: set[str] = {kind for kind, pat in _KIND_PATTERNS if pat.search(q)}

    # Terminsignal nötig; ein bloßes Listensignal zählt nur mit expliziter Kursart.
    if not _TERMIN_SIGNAL.search(q) and not (kinds and _LISTEN_SIGNAL.search(q)):
        return None

    # Standort (nur bekannte Orte aus termine.json)
    location = next((loc for key, loc in known_locations.items() if key in q), None)

    # Unbekannter Wunsch-Ort („in Frankfurt") → LLM soll Alternativen anbieten.
    for wort in _ORT_KANDIDAT.findall(q):
        wort = wort.strip(".-")
        if wort in known_locations or wort in _KEIN_ORT:
            continue
        return None

    # Stufe
    s12, s3 = bool(_STAGE_12.search(q)), bool(_STAGE_3.search(q))
    stage = "1+2" if s12 and not s3 else "3" if s3 and not s12 else None

    # „Kurs/Ausbildung" ohne Übungstage-Wort und ohne Ort: Übungstage ausblenden.
    if not kinds and not location and _KURS_WORT.search(q):
        kinds = {"presence", "hybrid"}

    if not location and not stage and not kinds:
        return None  # kein konkreter Filter → allgemeine Frage → LLM

    return {"location": location, "stage": stage, "kinds": kinds or None}


# ── 2 · Termine filtern (deterministisch) ────────────────────────────────────

def _select(seminars: list[dict], f: dict, today: str) -> list[dict]:
    out = [s for s in seminars if s.get("start", "") >= today]
    if f.get("location"):
        out = [s for s in out if s.get("location", "").lower() == f["location"].lower()]
    if f.get("stage"):
        out = [s for s in out if s.get("stage") == f["stage"]]
    if f.get("kinds"):
        out = [s for s in out if s.get("kind") in f["kinds"]]
    out.sort(key=lambda s: (s.get("start", ""), s.get("id", "")))
    return out


# ── 3 · Antwort formatieren (Regeln 2/4/5/8/9 des System-Prompts) ────────────

def _datum(s: dict) -> str:
    try:
        start = datetime.fromisoformat(s["start"])
        end = datetime.fromisoformat(s.get("end", s["start"]))
    except (KeyError, ValueError):
        return s.get("start", "?")
    if end != start:
        return f"{start.strftime('%d.%m.')}–{end.strftime('%d.%m.%Y')}"
    return start.strftime("%d.%m.%Y")


def _zeile(s: dict, f: dict, fett: bool) -> str:
    datum = f"**{_datum(s)}**" if fett else _datum(s)
    teile = [datum]
    label_gezeigt = not (f.get("kinds") and len(f["kinds"]) == 1)
    if label_gezeigt:
        teile.append(_KIND_LABEL.get(s.get("kind", ""), s.get("kind", "?")))
    teile.append(f"Stufe {s.get('stage', '?')}")
    ort = s.get("location", "?")
    # Ort nur, wenn kein Ortsfilter gesetzt ist — und „Live-Online" nicht doppelt
    # zum bereits gezeigten Label „Live-Online-Theorie".
    if not f.get("location") and not (label_gezeigt and ort == "Live-Online"):
        teile.append(ort)
    zeile = " · ".join(teile)
    if s.get("url"):
        zeile += f" — [Jetzt buchen]({s['url']})"
    return f"- {zeile}"


def _intro(f: dict, treffer: list[dict]) -> str:
    stufe = f" der Stufe {f['stage']}" if f.get("stage") else ""
    ort = f.get("location")
    if ort and all(s.get("kind") == "practice" for s in treffer):
        return (
            f"In {ort} finden die Präsenz-Übungstage{stufe} der DHI 2.0 Ausbildung "
            "statt — die Theorie dazu absolvieren Sie vorab live online. "
            "Die nächsten Termine:"
        )
    if ort:
        return f"Gern — die nächsten Termine{stufe} in {ort}:"
    kinds = f.get("kinds") or set()
    if kinds == {"practice"}:
        return f"Gern — die nächsten Präsenz-Übungstage{stufe} (DHI 2.0):"
    if kinds == {"presence"}:
        return f"Gern — die nächsten Vollpräsenz-Termine{stufe} (DHI 1.0) in Aschaffenburg:"
    if kinds == {"hybrid"}:
        return f"Gern — die nächsten Live-Online-Theorieblöcke{stufe} (DHI 2.0):"
    if f.get("stage"):
        return f"Gern — die nächsten Termine für Stufe {f['stage']}:"
    return "Gern — die nächsten passenden Termine:"


def _outro(f: dict, treffer: list[dict], weitere: int) -> str:
    saetze = []
    if (f.get("kinds") or set()) == {"hybrid"}:
        saetze.append("Die zugehörigen Präsenz-Übungstage buchen Sie separat dazu.")
    if weitere > 0:
        saetze.append(f"Alle weiteren Termine: [Zum Seminarkalender]({SEMINARKALENDER_URL}).")
    saetze.append(
        "Passt einer dieser Termine für Sie?" if len(treffer) > 1
        else "Passt dieser Termin für Sie?"
    )
    return " ".join(saetze)


def _format(treffer: list[dict], f: dict, gesamt: int) -> str:
    gezeigt = treffer[:_MAX_LISTE]
    zeilen = [_zeile(s, f, fett=(i == 0)) for i, s in enumerate(gezeigt)]
    return "\n".join(
        [_intro(f, gezeigt), "", *zeilen, "", _outro(f, gezeigt, gesamt - len(gezeigt))]
    )


# ── 4 · Einstiegspunkt ───────────────────────────────────────────────────────

def try_answer(message: str, today: str | None = None) -> dict | None:
    """Deterministische Antwort auf eine reine Terminlistenfrage —
    oder None, wenn die Frage zum LLM-Pfad gehört."""
    data = retrieval.get_termine()
    seminars = data.get("seminars", [])
    if not seminars:
        return None

    known = {}
    for s in seminars:
        loc = s.get("location", "")
        if loc and loc.lower() != "live-online":
            known[loc.lower()] = loc

    f = _parse(message, known)
    if f is None:
        return None

    treffer = _select(seminars, f, today or date.today().isoformat())
    if not treffer:
        return None  # z.B. „Vollpräsenz in Stuttgart" → LLM bietet Alternativen an

    sources, seen = [], set()
    for s in treffer[:_MAX_LISTE]:
        if s.get("url") and s["url"] not in seen:
            seen.add(s["url"])
            sources.append({"url": s["url"], "title": s.get("title", "Buchungsseite")})

    return {
        "reply": _format(treffer, f, len(treffer)),
        "sources": sources[:4],
        "mock": False,
        "deterministic": True,
    }
