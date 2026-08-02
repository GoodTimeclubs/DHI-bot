#!/usr/bin/env python3
"""Holt den aktuellen Seminarkalender live nach data/termine.json.

Der QS-Runner (tests/run_testkatalog.py) prüft Terminantworten gegen diese
Datei — etwa, ob der früheste passende Termin genannt wurde. In CI ist data/
leer, und die Fixtures im Repo sind ein eingefrorener Stand; damit gäbe es
Fehlalarme, sobald das Institut den Kalender ändert.

Deshalb vor dem Live-Lauf dieselbe Quelle ziehen, die auch der nächtliche
Crawl des Bots verwendet: die aus seminarkalender.html verlinkte
dhi-seminarkalender.js.

    python scripts/fetch_live_termine.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR  # noqa: E402
from app.crawler import fetch_kalender  # noqa: E402


def main() -> int:
    with httpx.Client() as client:
        kalender = fetch_kalender(client)

    seminars = kalender.get("seminars") or []
    if not seminars:
        print("!! Kein Termin aus dem Kalender-Script gelesen — der QS-Lauf wäre "
              "nicht aussagekräftig (Terminprüfungen liefen ins Leere).")
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ziel = DATA_DIR / "termine.json"
    ziel.write_text(json.dumps(kalender, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ {len(seminars)} Termine aus {kalender.get('js_url')} nach {ziel} übernommen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
