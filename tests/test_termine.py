"""Unit-Tests für die deterministischen Terminantworten (app/termine.py).

Absichert QS-Befund 8: Bei reinen Terminlistenfragen darf der früheste
passende Termin NIE fehlen — und Fragen, die Beratung brauchen (unbekannte
Orte, Preise, Konzeptfragen), müssen weiterhin an das LLM gehen (None).

Läuft ohne Server und ohne API-Key:
    pytest tests/test_termine.py -v
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.termine import KALENDER_BUTTON, SEMINARKALENDER_URL, try_answer  # noqa: E402

TODAY = "2026-07-30"  # fixer Stichtag: Tests bleiben stabil, egal wann sie laufen
TERMINE = json.loads((ROOT / "data" / "termine.json").read_text(encoding="utf-8"))

MD_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
DU_RE = re.compile(r"\b(du|dich|dir|dein\w*|euch|euer\w*|eure\w*)\b", re.I)


def _erwartete(kind=None, stage=None, location=None):
    """Referenzfilter unabhängig von der Implementierung."""
    res = [
        s for s in TERMINE["seminars"]
        if s["start"] >= TODAY
        and (kind is None or s["kind"] == kind)
        and (stage is None or s["stage"] == stage)
        and (location is None or location in s.get("orte", [s["location"]]))
    ]
    return sorted(res, key=lambda s: s["start"])


def _datum_de(iso: str) -> str:
    j, m, t = iso.split("-")
    return f"{t}.{m}."


# ── Kernfall des Befunds: frühester Termin darf nie fehlen ───────────────────

def test_uebungstage_leipzig_beginnen_beim_fruehesten():
    r = try_answer("Welche Übungstage gibt es in Leipzig?", today=TODAY)
    assert r is not None and r.get("deterministic")
    erwartet = _erwartete(kind="hybrid", location="Leipzig")
    assert erwartet[0]["start"] == "2027-06-07"  # Datenstand-Kontrolle
    assert _datum_de(erwartet[0]["start"]) in r["reply"]
    # chronologisch: der früheste steht vor allen weiteren genannten Daten
    pos = [r["reply"].find(_datum_de(s["start"])) for s in erwartet[:3]]
    pos = [p for p in pos if p >= 0]
    assert pos and pos[0] == min(pos)
    assert "Leipzig" in r["reply"]
    assert any("/seminare/" in u for _, u in MD_LINK.findall(r["reply"]))


def test_alle_filterkombinationen_enthalten_den_fruehesten():
    """Property-Test über alle sinnvollen Filter-Fragen: WENN deterministisch
    geantwortet wird, steht der früheste passende Termin in der Antwort."""
    orte = sorted({o for s in TERMINE["seminars"] for o in s["orte"] if o != "Online"})
    uebungsorte = {o for s in TERMINE["seminars"] if s["kind"] == "hybrid" for o in s["orte"]}
    fragen = []
    for ort in orte:
        fragen.append((f"Wann sind die nächsten Termine in {ort}?", dict(location=ort)))
        if ort in uebungsorte:
            fragen.append((f"Welche Übungstage gibt es in {ort}?", dict(kind="hybrid", location=ort)))
    for stage in ("1+2", "3", "1+2+3", "4"):
        fragen.append((f"Wann ist der nächste Termin für Stufe {stage}?", dict(stage=stage)))
    for stage in ("1+2", "3"):
        fragen.append((f"Welche Übungstage gibt es für Stufe {stage}?", dict(kind="hybrid", stage=stage)))
    fragen.append(("Wann startet die nächste Vollpräsenz-Ausbildung?", dict(kind="presence")))
    fragen.append(("Wann sind die nächsten Live-Hybrid-Termine?", dict(kind="hybrid")))
    fragen.append(("Wann sind die nächsten Live-Online-Termine?", dict(kind="online")))

    for frage, filt in fragen:
        erwartet = _erwartete(**filt)
        r = try_answer(frage, today=TODAY)
        assert r is not None, f"sollte deterministisch sein: {frage!r}"
        assert _datum_de(erwartet[0]["start"]) in r["reply"], (
            f"frühester Termin {erwartet[0]['start']} fehlt bei: {frage!r}\n{r['reply']}"
        )


def test_stufe3_kurs_listet_den_fruehesten_start_aller_formate():
    r = try_answer("Wann startet der nächste Stufe-3-Kurs?", today=TODAY)
    assert r is not None
    assert "18.01." in r["reply"]          # frühester Stufe-3-Start (Vollpräsenz Aschaffenburg)


def test_leipzig_nennt_auch_termine_auf_anfrage():
    """Nicht direkt buchbare Shop-Termine („Details und Anfrage") bleiben
    sichtbar, verlinken aber auf die Anfrage statt auf „Jetzt buchen"."""
    r = try_answer("Wann findet die nächste Ausbildung in Leipzig statt?", today=TODAY)
    assert r is not None
    assert "Leipzig" in r["reply"]
    assert "06.04." in r["reply"]          # frühester Leipzig-Termin (Vollpräsenz, auf Anfrage)
    assert "[Details und Anfrage](" in r["reply"]


def test_hybrid_mit_ortsfrage_ordnet_die_uebungstage_ein():
    r = try_answer("Welche Übungstage gibt es in Aschaffenburg?", today=TODAY)
    assert r is not None
    assert re.search(r"live online", r["reply"], re.I)  # Einordnung: Theorie online


# ── Gating: diese Fragen gehören weiterhin zum LLM ───────────────────────────

def test_unbekannter_ort_geht_ans_llm():
    assert try_answer("Gibt es auch Termine in Frankfurt?", today=TODAY) is None
    assert try_answer("Wann startet der nächste Kurs in Köln?", today=TODAY) is None


def test_preis_und_buchungsfragen_gehen_ans_llm():
    assert try_answer("Was kosten die Übungstage in Stuttgart?", today=TODAY) is None
    assert try_answer("Sind für den Septembertermin noch Plätze frei?", today=TODAY) is None
    assert try_answer("Kann ich den Termin in Raten zahlen?", today=TODAY) is None


def test_sitzungsfragen_gehen_ans_llm():
    """Wer eine Hypnose-Sitzung sucht, meint die DHI-Praxis, nicht die
    Ausbildung — das LLM muss zurückfragen können (Prompt-Regel 12), statt
    hier deterministisch Ausbildungstermine zu listen. Aschaffenburg ist
    beides: Ausbildungsort UND Praxisstandort."""
    assert try_answer("Ich möchte eine Hypnose. Wann haben Sie in Aschaffenburg einen Termin?",
                      today=TODAY) is None
    assert try_answer("Wann ist in Leipzig eine Sitzung möglich?", today=TODAY) is None
    assert try_answer("Wann kann ich als Klient nach Stuttgart kommen?", today=TODAY) is None


def test_konzept_und_inhaltsfragen_gehen_ans_llm():
    assert try_answer("Kann ich die Theorie auch komplett online machen?", today=TODAY) is None
    assert try_answer("Welche Inhalte lerne ich in der Stufe 1+2?", today=TODAY) is None
    assert try_answer("Was ist der Unterschied zwischen DHI 1.0 und DHI 2.0?", today=TODAY) is None


def test_uhrzeit_und_detailfragen_gehen_ans_llm():
    assert try_answer("Um wie viel Uhr beginnen die Übungstage in Stuttgart?", today=TODAY) is None
    assert try_answer("Finden die Übungstage am Wochenende statt?", today=TODAY) is None


def test_leeres_filterergebnis_geht_ans_llm():
    # Live-Hybrid-Übungstage gibt es nur in Aschaffenburg und Leipzig → LLM bietet Alternativen an
    assert try_answer("Wann ist die nächste Live-Hybrid-Ausbildung in Stuttgart?", today=TODAY) is None


def test_allgemeine_und_unklare_fragen_gehen_ans_llm():
    assert try_answer("Wann sind die nächsten Termine?", today=TODAY) is None  # kein Filter
    assert try_answer("asdf qwer yxcv ???", today=TODAY) is None
    assert try_answer("Hallo!", today=TODAY) is None


# ── Formatregeln des System-Prompts (Sie-Form, Links, Kürze) ─────────────────

def test_antwortformat_haelt_die_widget_regeln_ein():
    fragen = [
        "Welche Übungstage gibt es in Leipzig?",
        "Wann ist der nächste Termin für Stufe 1+2?",
        "Wann startet der nächste Stufe-3-Kurs?",
        "Wann findet die nächste Ausbildung in Leipzig statt?",
    ]
    for frage in fragen:
        r = try_answer(frage, today=TODAY)
        assert r is not None
        reply = r["reply"]
        plain = MD_LINK.sub(r"\1", reply)
        assert DU_RE.search(re.sub(r"https?://\S+", "", plain)) is None, f"Du-Form: {frage!r}"
        assert re.search(r"https?://", MD_LINK.sub("", reply)) is None, f"nackte URL: {frage!r}"
        assert MD_LINK.search(reply), f"kein Buchungslink: {frage!r}"
        assert "](tel:" not in reply and "](mailto:" not in reply
        assert len(re.findall(r"(?m)^- ", reply)) <= 3, f"zu viele Listenpunkte: {frage!r}"
        assert len(re.findall(r"\*\*[^*\n]+\*\*", reply)) <= 3, f"zu viel Fett: {frage!r}"
        assert len(plain.split()) <= 120, f"zu lang ({len(plain.split())} Wörter): {frage!r}"
        assert r["sources"], f"keine Quellen: {frage!r}"


def test_datumsbereich_format():
    r = try_answer("Welche Übungstage gibt es in Leipzig?", today=TODAY)
    assert "07.06.–11.06.2027" in r["reply"]


# ── Button zur Terminseite (Rückmeldung aus dem Live-Betrieb, 01.08.2026) ────

def test_jede_terminantwort_endet_mit_dem_seminarkalender_button():
    """„Bei Terminen immer ein Button am Ende auf weitere Termine zu der
    Terminseite." Das Widget rendert [Beschriftung](URL) als Button — steht der
    Link in der letzten Zeile, endet die Antwort sichtbar mit diesem Button."""
    fragen = [
        "Welche Übungstage gibt es in Leipzig?",
        "Wann ist der nächste Termin für Stufe 1+2?",
        "Wann startet der nächste Stufe-3-Kurs?",
        "Wann findet die nächste Ausbildung in Leipzig statt?",
        "Wann sind die nächsten Live-Online-Termine?",
    ]
    for frage in fragen:
        r = try_answer(frage, today=TODAY)
        assert r is not None, frage
        zeilen = [z for z in r["reply"].splitlines() if z.strip()]
        assert zeilen[-1] == KALENDER_BUTTON, f"kein Abschluss-Button bei: {frage!r}"
        assert r["reply"].count(f"]({SEMINARKALENDER_URL})") == 1, f"Link doppelt bei: {frage!r}"


def test_button_auch_wenn_alle_termine_gezeigt_wurden(monkeypatch):
    """Auch ohne „weitere" Termine soll der Weg in den Kalender offenstehen."""
    import app.termine as termine
    monkeypatch.setattr(termine.retrieval, "get_termine", lambda: {
        "seminars": [{
            "id": "t1", "kind": "hybrid", "stage": "1+2", "start": "2099-05-02",
            "end": "2099-05-03", "location": "Stuttgart", "orte": ["Stuttgart"],
            "url": "https://deutsches-hypnoseinstitut.de/seminare/1/",
        }],
        "notes": [], "fetched_at": "2099-01-01T00:00:00+00:00",
    })
    r = try_answer("Welche Übungstage gibt es in Stuttgart?", today=TODAY)
    assert r["reply"].splitlines()[-1] == KALENDER_BUTTON
    assert "weitere" not in r["reply"].lower()   # es gibt keine weiteren
    assert "Passt dieser Termin für Sie?" in r["reply"]
