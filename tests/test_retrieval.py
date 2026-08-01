"""Granulare Unit-Tests für die Retrieval-Logik (app/retrieval.py).

Absichert die Preis-Boost-Regeln aus v0.1–v0.3: Ausbildungs-Preisfragen
boosten die Ablefy-Buchungsseiten (und garantieren sie im Kontext),
Sitzungs-/Coaching-Preisfragen zu den DHI-Praxen tun das NICHT (v0.3.0-Guard,
sonst drängen Ausbildungspreise in Sitzungsantworten), und pro Seite landen
höchstens zwei Abschnitte im Kontext.

Läuft ohne Server, ohne API-Key, ohne Internet und ohne Index-Datei
(der Index wird pro Test durch ein Fake-Objekt ersetzt):
    pytest tests/test_retrieval.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.retrieval as retrieval  # noqa: E402


class _FakeBM25:
    """Liefert feste Scores, unabhängig von der Query."""

    def __init__(self, scores):
        self._scores = scores

    def get_scores(self, _tokens):
        return list(self._scores)


def _fake_index(chunks, scores):
    return {"chunks": chunks, "bm25": _FakeBM25(scores), "built_at": "test"}


PRAXIS = {"url": "https://hypnosepraxis-berlin.deutsches-hypnoseinstitut.de/",
          "title": "DHI Hypnosepraxis Berlin", "source": "website",
          "text": "Hypnose-Sitzung 180 €, 15 Minuten Beratung 0 €"}
BUCHUNG = {"url": "https://dhi2.de/s/d-hi/presence12",
           "title": "Stufe 1+2 Buchung", "source": "buchungsseite",
           "text": "Gesamtpreis 3.596 €, Skonto möglich"}
WISSEN = {"url": "https://deutsches-hypnoseinstitut.de/was-ist-hypnose.html",
          "title": "Was ist Hypnose", "source": "website",
          "text": "Hypnose ist ein kooperativer Prozess"}


def test_ausbildungspreisfrage_boostet_buchungsseite(monkeypatch):
    monkeypatch.setattr(retrieval, "_load_index",
                        lambda: _fake_index([PRAXIS, BUCHUNG, WISSEN], [1.0, 0.9, 0.5]))
    out = retrieval.search("Was kostet die Ausbildung Stufe 1+2?")
    # 0.9 × 1.8 = 1.62 schlägt die 1.0 der Praxis-Seite → Buchungsseite vorn
    assert out[0]["source"] == "buchungsseite"


def test_sitzungspreisfrage_boostet_nicht(monkeypatch):
    """v0.3.0-Guard: „Sitzung" in der Frage → kein Buchungsseiten-Boost,
    die Praxis-Seite bleibt der Top-Treffer."""
    monkeypatch.setattr(retrieval, "_load_index",
                        lambda: _fake_index([PRAXIS, BUCHUNG, WISSEN], [1.0, 0.9, 0.5]))
    out = retrieval.search("Was kostet eine Hypnose-Sitzung in Berlin?")
    assert out[0]["url"] == PRAXIS["url"]
    # und die Buchungsseite wird nicht künstlich dazugezwungen/verdoppelt
    assert [c["url"] for c in out].count(BUCHUNG["url"]) <= 1


def test_coachingfrage_boostet_ebenfalls_nicht(monkeypatch):
    monkeypatch.setattr(retrieval, "_load_index",
                        lambda: _fake_index([PRAXIS, BUCHUNG, WISSEN], [1.0, 0.9, 0.5]))
    out = retrieval.search("Was kostet ein Business-Coaching bei euch?")
    assert out[0]["url"] == PRAXIS["url"]


def test_preisfrage_garantiert_buchungsseite_im_kontext(monkeypatch):
    """Auch wenn die Buchungsseite von BM25 fast ignoriert wird, muss sie bei
    Ausbildungs-Preisfragen im Kontext landen (QS-Befund C1 aus v0.2.2)."""
    fuellseiten = [
        {"url": f"https://deutsches-hypnoseinstitut.de/seite-{i}.html",
         "title": f"Seite {i}", "source": "website", "text": "Ausbildung Inhalte"}
        for i in range(6)
    ]
    chunks = fuellseiten + [BUCHUNG]
    scores = [9, 8, 7, 6, 5, 4, 0.1]  # Buchungsseite fast unsichtbar
    monkeypatch.setattr(retrieval, "_load_index", lambda: _fake_index(chunks, scores))
    out = retrieval.search("Was kostet die Ausbildung?")
    assert any(c["source"] == "buchungsseite" for c in out)


def test_hoechstens_zwei_abschnitte_pro_seite(monkeypatch):
    gleiche_seite = [
        {"url": "https://deutsches-hypnoseinstitut.de/faq-ausbildung.html",
         "title": "FAQ", "source": "website", "text": f"Abschnitt {i}"}
        for i in range(4)
    ]
    andere = [{"url": "https://deutsches-hypnoseinstitut.de/ueber.html",
               "title": "Über", "source": "website", "text": "Über das DHI"}]
    monkeypatch.setattr(retrieval, "_load_index",
                        lambda: _fake_index(gleiche_seite + andere, [5, 4, 3, 2, 1]))
    out = retrieval.search("Fragen zur Hypnoseausbildung")
    faq_treffer = [c for c in out if c["url"].endswith("faq-ausbildung.html")]
    assert len(faq_treffer) == 2          # max. 2 Abschnitte derselben Seite
    assert any(c["url"].endswith("ueber.html") for c in out)  # Vielfalt bleibt


def test_leerer_index_liefert_leere_liste(monkeypatch):
    monkeypatch.setattr(retrieval, "_load_index", lambda: None)
    assert retrieval.search("egal") == []
