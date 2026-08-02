#!/usr/bin/env python3
"""Holt den Terminstand des Live-Bots nach data/termine.json.

Der QS-Runner (tests/run_testkatalog.py) prüft Terminantworten gegen diese
Datei — etwa, ob der früheste passende Termin genannt wurde. In CI ist data/
leer, und die Fixtures im Repo sind ein eingefrorener Stand.

Die Daten kommen deshalb über `GET /api/termine` vom Bot selbst. Zwei Gründe:

  • Der direkte Weg über die Website scheitert aus GitHub Actions heraus —
    `deutsches-hypnoseinstitut.de` nimmt vom Runner keine Verbindung an
    (offenbar werden Rechenzentrums-IPs geblockt).
  • Er ist auch der richtigere: Geprüft wird gegen genau die Termine, die der
    Bot kennt. Sonst könnte der Katalog Fälle melden, die nur daran liegen,
    dass der nächtliche Crawl eine Kalenderänderung noch nicht aufgenommen hat
    — dafür ist der Smoke-Test mit seiner Index-Altersprüfung zuständig.

    python scripts/fetch_live_termine.py --base-url https://bot.deutsches-hypnoseinstitut.de
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR  # noqa: E402

BOT_URL = "https://bot.deutsches-hypnoseinstitut.de"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("BOT_URL", BOT_URL))
    args = ap.parse_args()
    base_url = args.base_url.rstrip("/")

    try:
        r = httpx.get(f"{base_url}/api/termine", timeout=30, follow_redirects=True)
    except Exception as e:  # noqa: BLE001
        print(f"!! {base_url}/api/termine nicht erreichbar: {type(e).__name__}: {e}")
        return 1

    if r.status_code == 404:
        print(f"!! {base_url} kennt /api/termine noch nicht — läuft dort ein Stand vor v0.3.2?")
        return 1
    if r.status_code != 200:
        print(f"!! {base_url}/api/termine antwortet mit HTTP {r.status_code}: {r.text[:200]}")
        return 1

    kalender = r.json()
    seminars = kalender.get("seminars") or []
    if not seminars:
        print("!! Der Bot meldet keine Termine — der QS-Lauf wäre nicht aussagekräftig "
              "(alle Terminprüfungen liefen ins Leere).")
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ziel = DATA_DIR / "termine.json"
    ziel.write_text(json.dumps(kalender, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ {len(seminars)} Termine von {base_url} übernommen "
          f"(Stand {kalender.get('fetched_at', 'unbekannt')}) → {ziel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
