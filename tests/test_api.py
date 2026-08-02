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

from app.config import DATA_DIR  # noqa: E402
from app.main import app  # noqa: E402

# TestClient bewusst ohne Kontextmanager: so bleibt der Lifespan aus und der
# Hintergrund-Scheduler (täglicher Re-Crawl) startet im Test nicht mit.
client = TestClient(app)

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "termine.json").exists(),
    reason="data/termine.json fehlt — erst 'python -m app.crawler --from-fixtures' ausführen",
)


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
