"""Unit-Tests für die HTTP-Endpunkte /api/health und /api/termine.

Absichert vor allem `/api/termine` (v0.3.2): Der QS-Lauf der CI/CD-Pipeline
holt sich darüber die Solldaten für die Terminprüfungen — verschwindet der
Endpunkt oder ändert sich sein Schema, ist der komplette QS-Lauf wertlos,
ohne dass es sonst irgendwo auffiele.

Läuft ohne Server, ohne API-Key und ohne Internet, braucht aber die
Daten in data/ (notfalls per `python -m app.crawler --from-fixtures`
und `python -c "from app.indexer import build_index; build_index()"`):

    pytest tests/test_api.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402
from app.config import DATA_DIR  # noqa: E402
from app.main import app  # noqa: E402

# TestClient bewusst ohne Kontextmanager: so bleibt der Lifespan aus und der
# Hintergrund-Scheduler (täglicher Re-Crawl) startet im Test nicht mit.
client = TestClient(app)

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "index.pkl").exists(),
    reason="data/ fehlt — erst 'python -m app.crawler --from-fixtures' und den Indexer ausführen",
)


@pytest.fixture(autouse=True)
def _zaehler_zuruecksetzen():
    """Rate-Limit- und Tageszähler liegen im Modulzustand — pro Test leeren."""
    main._hits.clear()
    main._daily.update(date="", count=0, test_count=0)
    yield
    main._hits.clear()
    main._daily.update(date="", count=0, test_count=0)


def test_health_meldet_datenstand():
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    # Felder, auf die sich der Smoke-Test der Pipeline verlässt:
    for feld in ("model", "mock_mode", "index_built_at", "chunks", "termine"):
        assert feld in d, f"{feld} fehlt in /api/health"
    assert d["termine"] > 0


def test_termine_liefert_den_kalender():
    r = client.get("/api/termine")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    d = r.json()

    seminars = d.get("seminars")
    assert seminars, "keine Termine im Endpunkt"
    pflichtfelder = {"id", "kind", "stage", "title", "start", "location", "url"}
    fehlend = pflichtfelder - set(seminars[0])
    assert not fehlend, f"Termin ohne Pflichtfelder: {fehlend}"


def test_termine_entspricht_der_datei():
    """Der Endpunkt darf nichts umformen — der QS-Lauf vergleicht damit."""
    vom_endpunkt = client.get("/api/termine").json()
    von_platte = json.loads((DATA_DIR / "termine.json").read_text(encoding="utf-8"))
    assert vom_endpunkt == von_platte


def test_termine_zahl_passt_zu_health():
    health = client.get("/api/health").json()
    seminars = client.get("/api/termine").json()["seminars"]
    assert health["termine"] == len(seminars)


# ── QS-Läufe auf getrenntem API-Schlüssel ───────────────────────────────────
# Der Testkatalog stellt echte Chat-Anfragen an den Live-Bot. Ohne getrennten
# Schlüssel ginge jeder Lauf vom Produktivguthaben ab — wäre das leer, könnte
# der Bot echten Besuchern nicht mehr antworten. Diese Tests sichern, dass der
# Testpfad nur mit gültigem Token offensteht, ohne eigenen Schlüssel gar nicht
# antwortet und die Kostenbremse für echte Besucher nicht anfasst.

@pytest.fixture
def qs(monkeypatch):
    """Server mit konfiguriertem QS-Zugang; llm.answer wird nicht wirklich gerufen."""
    monkeypatch.setattr(main, "TEST_TOKEN", "qs-geheim")
    monkeypatch.setattr(main, "ANTHROPIC_API_KEY_TEST", "sk-test-schluessel")
    aufrufe = []

    def fake_answer(message, history, api_key=None):
        aufrufe.append({"message": message, "api_key": api_key})
        return {"reply": "Antwort.", "sources": [], "mock": False}

    monkeypatch.setattr(main.llm, "answer", fake_answer)
    return aufrufe


def test_health_meldet_getrennten_qs_schluessel(qs):
    d = client.get("/api/health").json()
    assert d["test_key_configured"] is True
    assert d["test_messages_today"] == 0


def test_ohne_konfiguration_meldet_health_keinen_qs_schluessel():
    d = client.get("/api/health").json()
    assert d["test_key_configured"] is False


def test_falscher_test_token_wird_abgewiesen(qs):
    r = client.post("/api/chat", json={"message": "Was kostet die Stufe 3?"},
                    headers={"X-DHI-Test": "falsch"})
    assert r.status_code == 403
    assert not qs, "Bei falschem Token darf keine Modellanfrage entstehen"


def test_test_token_ohne_schluessel_antwortet_nicht(monkeypatch):
    """Lieber 503 als still auf den Produktivschlüssel ausweichen."""
    monkeypatch.setattr(main, "TEST_TOKEN", "qs-geheim")
    monkeypatch.setattr(main, "ANTHROPIC_API_KEY_TEST", "")
    r = client.post("/api/chat", json={"message": "Was kostet die Stufe 3?"},
                    headers={"X-DHI-Test": "qs-geheim"})
    assert r.status_code == 503
    assert "Produktivguthaben" in r.json()["detail"]


def test_qs_anfrage_laeuft_ueber_den_test_schluessel(qs):
    r = client.post("/api/chat", json={"message": "Was kostet die Stufe 3?"},
                    headers={"X-DHI-Test": "qs-geheim"})
    assert r.status_code == 200
    assert len(qs) == 1
    assert qs[0]["api_key"] == "sk-test-schluessel"


def test_normale_anfrage_laeuft_ohne_test_schluessel(qs):
    r = client.post("/api/chat", json={"message": "Was kostet die Stufe 3?"})
    assert r.status_code == 200
    assert qs[0]["api_key"] is None, "ohne Header muss der Produktivpfad greifen"


def test_qs_anfragen_umgehen_rate_limit_und_tageslimit(qs, monkeypatch):
    # Tageslimit künstlich auf 1 setzen: Ein QS-Lauf darf es weder auslösen
    # noch aufbrauchen — sonst bekämen echte Besucher die Limit-Antwort.
    monkeypatch.setattr(main, "DAILY_MESSAGE_LIMIT", 1)
    kopf = {"X-DHI-Test": "qs-geheim"}
    for _ in range(25):  # weit über dem IP-Limit von 20 / 5 Min
        r = client.post("/api/chat", json={"message": "Testfrage"}, headers=kopf)
        assert r.status_code == 200, "QS-Verkehr darf nicht ins Rate-Limit laufen"

    d = client.get("/api/health").json()
    assert d["messages_today"] == 0, "QS-Anfragen dürfen die Kostenbremse nicht belasten"
    assert d["test_messages_today"] == 25

    # Echte Besucher haben ihr Kontingent dadurch unverändert zur Verfügung.
    echt = client.post("/api/chat", json={"message": "Was kostet die Stufe 3?"})
    assert echt.json()["reply"] != main._LIMIT_REPLY
