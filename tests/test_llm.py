"""Granulare Unit-Tests für Prompt-Regeln und Prompt-Bausteine (app/llm.py).

Absichert, dass die QS-kritischen Regeln nicht versehentlich aus dem
System-Prompt verschwinden (fester WhatsApp-Link, Preis-Trennung
Ausbildung/Praxis, Link-Pflichten aus dem QS-Lauf 01.08.), dass alle
Platzhalter befüllt werden und dass der deterministische PREISDATEN-Block
auch neue Ablefy-Produkte (unbekannte product_keys) sauber aufnimmt.

Läuft ohne Server, ohne API-Key und ohne Internet:
    pytest tests/test_llm.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.llm as llm  # noqa: E402


# ── Kernregeln müssen wörtlich im Prompt stehen ──────────────────────────────

def test_prompt_enthaelt_kernregeln():
    t = llm.SYSTEM_TEMPLATE
    kernregeln = (
        # fester WhatsApp-Baustein (QS-Befund: Modell baute Zahlendreher)
        "[Beratung per WhatsApp]({whatsapp_link})",
        # Praxen-Netzwerk mit festem Link (v0.3.0)
        "[Zu den DHI-Praxen](https://praxen.deutsches-hypnoseinstitut.de/)",
        # strikte Trennung Ausbildungs- vs. Sitzungspreise (v0.3.0)
        "vermische beides nie",
        # Ausbildungspreis → Buchungsseite Pflicht (QS-Lauf 01.08.: C1/C6)
        "KEIN Ersatz",
        # Praxis-Preis → Praxis-Link (QS-Lauf 01.08.: G2)
        "[Zur Hypnosepraxis Berlin](https://hypnosepraxis-berlin.deutsches-hypnoseinstitut.de/)",
        # Buchungsfrage → nie nur WhatsApp (QS-Lauf 01.08.: C5)
        "Telefon/WhatsApp sind dabei Ergänzung, nie Ersatz",
        # Rechenverbot und Sie-Form
        "Rechne NIEMALS selbst",
        "durchgängig die Sie-Form",
        # Institut behandelt nicht
        "Das Ausbildungsinstitut selbst behandelt nicht",
        # Nachschärfungen aus QS-Runde 2 (01.08., 40/49):
        "absolute Obergrenze 100 Wörter",
        "verlinke JEDEN genannten Bestandteil",
        "[Zum Hypnotiseurverzeichnis](https://hypnospathie.deutsches-hypnoseinstitut.de/verzeichnis.html)",
        # Nachschärfungen aus QS-Runde 3 (01.08., 46/49):
        "kein Aufsatz",
        "sind NICHT automatisch der Praxis-Kontakt",
    )
    for regel in kernregeln:
        assert regel in t, f"Kernregel fehlt im System-Prompt: {regel!r}"


def test_prompt_verbietet_selbst_konstruierte_kontaktlinks():
    t = llm.SYSTEM_TEMPLATE
    assert "konstruiere NIEMALS selbst wa.me-, tel:- oder mailto:-Links" in t


# ── build_system: alle Platzhalter befüllt, Kontaktdaten korrekt ─────────────

def _fake_termine():
    return {
        "seminars": [
            {"kind": "presence", "stage": "1+2", "start": "2099-01-05",
             "end": "2099-01-09", "time": "09:30", "location": "Aschaffenburg",
             "url": "https://dhi2.de/s/d-hi/test"},
        ],
        "notes": [],
        "fetched_at": "2099-01-01T00:00:00+00:00",
    }


def _fake_buchungsseite(product_key="presence12", title="DHI 1.0 Buchung"):
    return {
        "source": "buchungsseite",
        "product_key": product_key,
        "title": title,
        "url": f"https://dhi2.de/s/d-hi/{product_key}",
        "text": "Gesamtpreis 3.596,00 € inkl. MwSt.\nSkonto bei Einmalzahlung\nDer Betrag wird in 4 Monatsraten beglichen",
    }


def test_build_system_fuellt_alle_platzhalter(monkeypatch):
    monkeypatch.setattr(llm.retrieval, "get_termine", _fake_termine)
    monkeypatch.setattr(llm.retrieval, "get_pages", lambda: [_fake_buchungsseite()])
    out = llm.build_system([
        {"title": "Praxis Berlin", "url": "https://hypnosepraxis-berlin.deutsches-hypnoseinstitut.de/",
         "text": "Hypnose-Sitzung 180 €"},
    ])
    for platzhalter in ("{today}", "{termine}", "{termine_stand}", "{preise}",
                        "{context}", "{telefon}", "{whatsapp}", "{whatsapp_link}", "{email}"):
        assert platzhalter not in out, f"Platzhalter nicht befüllt: {platzhalter}"
    assert "06021 920 8003" in out                      # Telefon als Text
    assert "https://wa.me/4915154434470" in out         # einzig erlaubter WhatsApp-Link
    assert "05.01." in out                              # Termin formatiert
    assert "Hypnose-Sitzung 180 €" in out               # Kontext-Auszug
    assert "3.596" in out                               # PREISDATEN-Block


# ── PREISDATEN-Block: neue Produkte, wörtliche Zeilen ────────────────────────

def test_format_preise_faellt_bei_unbekanntem_produkt_auf_den_seitentitel(monkeypatch):
    """Neue Ablefy-Produkte (z.B. expertReinkarnation, seit 01.08. im Kalender)
    haben keinen Eintrag in PRODUCT_LABEL — der Block muss trotzdem Label,
    Buchungslink und wörtliche Preiszeilen enthalten."""
    seite = {
        "source": "buchungsseite",
        "product_key": "expertReinkarnation",
        "title": "DHI Experteseminar Reinkarnation – Buchung",
        "url": "https://dhi2.de/s/d-hi/reinkarnation-test",
        "text": "DHI Experteseminar Reinkarnation\n499,00 € inkl. MwSt.\nDer Betrag wird in 4 Monatsraten beglichen",
    }
    monkeypatch.setattr(llm.retrieval, "get_pages", lambda: [seite])
    out = llm.format_preise()
    assert "Reinkarnation" in out                       # Fallback auf Seitentitel
    assert "https://dhi2.de/s/d-hi/reinkarnation-test" in out
    assert "499,00 €" in out                            # wörtliche Preiszeile
    assert "Monatsraten" in out                         # wörtliche Ratenzeile


def test_format_preise_ignoriert_websiteseiten(monkeypatch):
    monkeypatch.setattr(llm.retrieval, "get_pages", lambda: [
        {"source": "website", "title": "Praxis", "url": "https://x/", "text": "Sitzung 180 €"},
    ])
    out = llm.format_preise()
    assert "180" not in out  # Praxis-Preise gehören NICHT in die Ausbildungs-PREISDATEN


# ── Termin-Baustein: nummeriert und chronologisch ────────────────────────────

def test_format_termine_nummeriert_chronologisch(monkeypatch):
    daten = _fake_termine()
    daten["seminars"] = [
        {"kind": "hybrid", "stage": "3", "start": "2099-06-01", "end": "2099-06-04",
         "location": "Live-Online", "url": "https://dhi2.de/s/b"},
        {"kind": "presence", "stage": "1+2", "start": "2099-01-05", "end": "2099-01-09",
         "location": "Aschaffenburg", "url": "https://dhi2.de/s/a"},
    ]
    monkeypatch.setattr(llm.retrieval, "get_termine", lambda: daten)
    text, stand = llm.format_termine()
    zeilen = [z for z in text.splitlines() if z[:2] in ("1.", "2.")]
    assert len(zeilen) == 2
    assert "05.01.2099" in zeilen[0]  # frühester Termin steht an Position 1
    assert "01.06.2099" in zeilen[1]
    assert stand == daten["fetched_at"]


# ── Stilfilter: keine Gedankenstriche in Bot-Antworten (v0.3.1) ──────────────

def test_prompt_verbietet_gedankenstriche():
    t = llm.SYSTEM_TEMPLATE
    assert "KEINE Gedankenstriche" in t                 # Regel 9 (FORMAT)
    assert "Keine Gedankenstriche" in t                 # ERINNERUNG-Block
    # Das Stilbeispiel lebt die Regel vor (Vorbildwirkung auf das Modell):
    beispiel = t.split("STILBEISPIEL")[1].split("TERMINDATEN")[0]
    assert "—" not in beispiel


def test_filter_ersetzt_gedankenstriche_durch_komma():
    f = llm._ohne_gedankenstriche
    assert f("Wir sind da — gern auch persönlich.") == "Wir sind da, gern auch persönlich."
    assert f("Wir sind da – gern auch persönlich.") == "Wir sind da, gern auch persönlich."
    assert f("Ein Einschub—ohne Leerzeichen.") == "Ein Einschub, ohne Leerzeichen."
    assert f("Der Kurs — auch DHI 1.0 genannt — startet bald.") == \
        "Der Kurs, auch DHI 1.0 genannt, startet bald."


def test_filter_erhaelt_bis_striche_in_daten_und_zahlen():
    f = llm._ohne_gedankenstriche
    assert f("Termin 05.01.–09.01.2099 in Aschaffenburg.") == \
        "Termin 05.01.–09.01.2099 in Aschaffenburg."
    assert f("Geöffnet 10 – 17 Uhr.") == "Geöffnet 10–17 Uhr."
    assert f("Stufe 1+2 vom 21.09.—25.09.2026.") == "Stufe 1+2 vom 21.09.–25.09.2026."


def test_filter_streicht_strich_nach_satzzeichen_und_am_rand():
    f = llm._ohne_gedankenstriche
    assert f("Am 21.09. – also bald.") == "Am 21.09. also bald."
    assert f("— Erstens\n— Zweitens") == "- Erstens\n- Zweitens"
    assert f("Ein Satz endet offen —\nNeue Zeile.") == "Ein Satz endet offen\nNeue Zeile."


def test_answer_wendet_stilfilter_auf_jede_antwort_an(monkeypatch):
    monkeypatch.setattr(llm, "MOCK_LLM", True)
    monkeypatch.setattr(llm, "DETERMINISTIC_TERMINE", False)
    monkeypatch.setattr(llm.retrieval, "search", lambda q, k=6: [])
    monkeypatch.setattr(
        llm, "_mock_reply",
        lambda m, c: "Klar — das passt. Termin 05.01.–09.01.2099 — jetzt buchen.",
    )
    out = llm.answer("Testfrage?", [])
    assert "—" not in out["reply"]
    assert out["reply"].startswith("Klar, das passt.")
    assert "05.01.–09.01.2099" in out["reply"]          # Bis-Strich bleibt


def test_deterministische_terminantworten_sind_gedankenstrichfrei(monkeypatch):
    import app.termine as termine
    monkeypatch.setattr(llm, "DETERMINISTIC_TERMINE", True)
    monkeypatch.setattr(
        termine.retrieval, "get_termine",
        lambda: {"seminars": [
            {"kind": "practice", "stage": "1+2", "start": "2099-05-02",
             "end": "2099-05-03", "location": "Stuttgart",
             "url": "https://dhi2.de/s/d-hi/test", "id": "t1", "title": "Übungstage"},
        ], "notes": [], "fetched_at": "2099-01-01T00:00:00+00:00"},
    )
    out = llm.answer("Welche Übungstage gibt es in Stuttgart?", [])
    assert out.get("deterministic") is True
    assert "—" not in out["reply"]
    assert "02.05.–03.05.2099" in out["reply"]          # Bis-Strich im Datum bleibt
