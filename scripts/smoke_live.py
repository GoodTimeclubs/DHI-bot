#!/usr/bin/env python3
"""Smoke-Test gegen den Live-Bot — läuft nach jedem Deployment.

Prüft in wenigen Sekunden und ohne eine einzige Chat-Anfrage (also ohne
API-Kosten), ob der ausgerollte Stand tatsächlich benutzbar ist:

  1. `GET /api/health`  — erreichbar, echter Claude-Betrieb statt Mock-Modus,
     Index und Termine vorhanden, Index nicht veraltet (der nächtliche
     Re-Crawl um 03:10 Uhr muss durchlaufen — bleibt `index_built_at` stehen,
     ist er gescheitert).
  2. `GET /widget.js`   — wird ausgeliefert, enthält die öffentliche API
     `window.DHIBot` und trägt den kurzen Cache-Header (5 Minuten), damit
     Widget-Updates ohne HTML-Änderung greifen.
  3. CORS               — für jede Origin, auf der das Widget eingebunden ist,
     wird ein echter Preflight (`OPTIONS /api/chat`) geschickt. Genau hier
     scheitert der Chat stumm, wenn eine Subdomain in `ALLOWED_ORIGINS`
     fehlt — Wildcards greifen dort nicht. Gegenprobe mit einer fremden
     Origin: die muss abgelehnt werden (sonst steht wieder `*` in der .env).
  4. Widget-Einbau      — Zusatzprüfung auf den öffentlichen Seiten selbst:
     Ist das Snippet eingebunden? Das liegt beim Website-Betreiber, deshalb
     nur ein Hinweis, kein Fehlschlag.

Aufruf:
    python scripts/smoke_live.py --base-url https://bot.deutsches-hypnoseinstitut.de

Exit-Code 0 = alle harten Prüfungen bestanden, 1 = mindestens eine gescheitert.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

BOT_URL = "https://bot.deutsches-hypnoseinstitut.de"

# Alle Domains, auf denen das Widget eingebunden ist bzw. wird.
SUBDOMAINS = [
    "lars",
    "nautilus-code",
    "hypnospathie",
    "hypnosepraxis-aschaffenburg",
    "hypnosepraxis-berlin",
    "hypnosepraxis-oberstaufen",
    "praxen",
    "hybrid",
    "experte",
    "legal",
]
HAUPTDOMAIN = "deutsches-hypnoseinstitut.de"
ORIGINS = (
    [f"https://{HAUPTDOMAIN}", f"https://www.{HAUPTDOMAIN}"]
    + [f"https://{s}.{HAUPTDOMAIN}" for s in SUBDOMAINS]
)
FREMDE_ORIGIN = "https://beispiel-fremde-seite.example"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

ergebnisse: list[tuple[str, str, str]] = []  # (status, prüfung, info)


def merke(ok: bool | None, pruefung: str, info: str = "") -> bool:
    """ok=True → PASS, ok=False → FAIL, ok=None → WARN (kein Fehlschlag)."""
    status = "PASS" if ok else ("WARN" if ok is None else "FAIL")
    ergebnisse.append((status, pruefung, info))
    zeichen = {"PASS": "✓", "WARN": "≈", "FAIL": "✗"}[status]
    print(f"  {zeichen} {status:4} {pruefung}" + (f" — {info}" if info else ""))
    return status != "FAIL"


# ── 1 · Health ──────────────────────────────────────────────────────────────

def pruefe_health(client: httpx.Client, base_url: str, max_alter_h: float) -> None:
    print("\nHealth")
    try:
        r = client.get(f"{base_url}/api/health", timeout=20)
    except Exception as e:  # noqa: BLE001
        merke(False, "/api/health erreichbar", f"{type(e).__name__}: {e}")
        return
    if r.status_code != 200:
        merke(False, "/api/health erreichbar", f"HTTP {r.status_code}")
        return
    d = r.json()
    merke(d.get("status") == "ok", "Status", str(d.get("status")))
    merke(
        d.get("mock_mode") is False,
        "Echter Claude-Betrieb (kein Mock-Modus)",
        f"Modell {d.get('model')}",
    )
    merke((d.get("chunks") or 0) > 0, "Index gefüllt", f"{d.get('chunks')} Abschnitte")
    merke((d.get("termine") or 0) > 0, "Termine geladen", f"{d.get('termine')} Termine")
    merke(
        bool(d.get("deterministic_termine")),
        "Deterministische Terminantworten aktiv",
        str(d.get("deterministic_termine")),
    )
    # Nur ein Hinweis: Der Bot funktioniert auch ohne getrennten QS-Schlüssel —
    # dann geht aber jeder Testkatalog-Lauf vom Produktivguthaben ab.
    merke(
        True if d.get("test_key_configured") else None,
        "QS-Läufe auf getrenntem API-Schlüssel",
        "" if d.get("test_key_configured")
        else "ANTHROPIC_API_KEY_TEST/TEST_TOKEN fehlen auf dem Server — "
             "der Testkatalog verbraucht sonst Produktivguthaben",
    )

    gebaut = d.get("index_built_at")
    if not gebaut:
        merke(False, "Index-Zeitstempel vorhanden", "index_built_at fehlt")
        return
    try:
        ts = datetime.fromisoformat(str(gebaut).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except ValueError:
        merke(False, "Index-Zeitstempel lesbar", str(gebaut))
        return
    alter = datetime.now(timezone.utc) - ts
    merke(
        alter <= timedelta(hours=max_alter_h),
        f"Index jünger als {max_alter_h:g} h",
        f"gebaut {ts:%d.%m.%Y %H:%M} UTC, Alter {alter.total_seconds() / 3600:.1f} h"
        + ("" if alter <= timedelta(hours=max_alter_h) else " — nächtlicher Re-Crawl gescheitert?"),
    )


# ── 2 · Widget-Auslieferung ─────────────────────────────────────────────────

def pruefe_widget(client: httpx.Client, base_url: str) -> None:
    print("\nWidget-Auslieferung")
    try:
        r = client.get(f"{base_url}/widget.js", timeout=20)
    except Exception as e:  # noqa: BLE001
        merke(False, "/widget.js erreichbar", f"{type(e).__name__}: {e}")
        return
    if not merke(r.status_code == 200, "/widget.js erreichbar", f"HTTP {r.status_code}"):
        return
    merke("DHIBot" in r.text, "Öffentliche API window.DHIBot enthalten")
    cache = r.headers.get("cache-control", "")
    merke("max-age=300" in cache.replace(" ", ""), "Cache-Control 5 Minuten", cache or "kein Header")


# ── 3 · CORS ────────────────────────────────────────────────────────────────

def preflight(client: httpx.Client, base_url: str, origin: str) -> tuple[int, str, str]:
    """→ (Status, access-control-allow-origin, Fehlertext)."""
    try:
        r = client.options(
            f"{base_url}/api/chat",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
            timeout=20,
        )
    except Exception as e:  # noqa: BLE001
        return 0, "", f"{type(e).__name__}: {e}"
    return r.status_code, r.headers.get("access-control-allow-origin", ""), ""


def pruefe_cors(client: httpx.Client, base_url: str, origins: list[str]) -> None:
    print(f"\nCORS — Preflight auf /api/chat für {len(origins)} Origins")
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        antworten = list(ex.map(lambda o: (o, preflight(client, base_url, o)), origins))
    for origin, (code, erlaubt, fehler) in antworten:
        kurz = origin.replace("https://", "")
        if fehler:
            merke(False, f"CORS {kurz}", f"nicht prüfbar — {fehler}")
        elif erlaubt == "*":
            merke(False, f"CORS {kurz}", "Server antwortet mit '*' — ALLOWED_ORIGINS ist nicht eingeschränkt")
        else:
            merke(code == 200 and erlaubt == origin, f"CORS {kurz}",
                  f"HTTP {code}, allow-origin: {erlaubt or '—'}")

    code, erlaubt, fehler = preflight(client, base_url, FREMDE_ORIGIN)
    if fehler:
        merke(False, "Fremde Origin wird abgewiesen", f"nicht prüfbar — {fehler}")
    else:
        merke(
            erlaubt == "" and code != 200,
            "Fremde Origin wird abgewiesen",
            f"HTTP {code}, allow-origin: {erlaubt or '—'}",
        )


# ── 4 · Widget-Einbau auf den Websites (nur Hinweis) ────────────────────────

def pruefe_einbau(client: httpx.Client, base_url: str) -> None:
    print("\nWidget-Einbau auf den Websites (Hinweis, kein Fehlschlag)")
    hosts = [HAUPTDOMAIN] + [f"{s}.{HAUPTDOMAIN}" for s in SUBDOMAINS]

    def hole(host: str) -> tuple[str, str]:
        try:
            r = client.get(f"https://{host}/", headers={"User-Agent": BROWSER_UA},
                           timeout=20, follow_redirects=True)
            if r.status_code != 200:
                return host, f"HTTP {r.status_code}"
            return host, "ok" if "widget.js" in r.text else "fehlt"
        except Exception as e:  # noqa: BLE001
            return host, type(e).__name__

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        befunde = list(ex.map(hole, hosts))

    unpruefbar: list[tuple[str, str]] = []
    for host, info in befunde:
        if info == "ok":
            merke(True, f"Snippet auf {host}")
        elif info == "fehlt":
            merke(None, f"Snippet fehlt auf {host}")
        else:
            unpruefbar.append((host, info))

    # Aus GitHub Actions heraus ist das der Normalfall: Die Website liegt bei
    # Hostinger und nimmt von Rechenzentrums-IPs keine Verbindung an. Deshalb
    # eine gesammelte Zeile statt elf Einzelwarnungen — aussagekräftig wird
    # diese Prüfung, wenn das Skript von einem normalen Anschluss aus läuft.
    if unpruefbar:
        kurz = [h.replace(f".{HAUPTDOMAIN}", "").replace(HAUPTDOMAIN, "(Hauptdomain)")
                for h, _ in unpruefbar]
        gruende = sorted({g for _, g in unpruefbar})
        merke(None, f"{len(unpruefbar)} von {len(hosts)} Domains nicht prüfbar",
              f"{', '.join(gruende)} — {', '.join(kurz)}")


# ── Zusammenfassung ─────────────────────────────────────────────────────────

def schreibe_summary(base_url: str) -> None:
    pfad = os.environ.get("GITHUB_STEP_SUMMARY")
    if not pfad:
        return
    fails = [e for e in ergebnisse if e[0] == "FAIL"]
    warns = [e for e in ergebnisse if e[0] == "WARN"]
    kopf = "❌ Smoke-Test fehlgeschlagen" if fails else "✅ Smoke-Test bestanden"
    with open(pfad, "a", encoding="utf-8") as f:
        f.write(f"## {kopf}\n\n`{base_url}` · {len(ergebnisse) - len(fails) - len(warns)} bestanden, "
                f"{len(fails)} Fehler, {len(warns)} Hinweise\n\n")
        if fails or warns:
            f.write("| | Prüfung | Info |\n|---|---|---|\n")
            for status, pruefung, info in fails + warns:
                f.write(f"| {'❌' if status == 'FAIL' else '⚠️'} | {pruefung} | {info} |\n")
            f.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("BOT_URL", BOT_URL))
    ap.add_argument("--max-index-alter-h", type=float, default=36.0,
                    help="Höchstalter des Index in Stunden (nächtlicher Crawl: ~24 h)")
    ap.add_argument("--ohne-einbau-check", action="store_true",
                    help="Prüfung der Website-Einbindung überspringen")
    args = ap.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"Smoke-Test gegen {base_url}")

    with httpx.Client(follow_redirects=True) as client:
        pruefe_health(client, base_url, args.max_index_alter_h)
        pruefe_widget(client, base_url)
        pruefe_cors(client, base_url, ORIGINS)
        if not args.ohne_einbau_check:
            pruefe_einbau(client, base_url)

    fails = [e for e in ergebnisse if e[0] == "FAIL"]
    warns = [e for e in ergebnisse if e[0] == "WARN"]
    print(f"\nErgebnis: {len(ergebnisse) - len(fails) - len(warns)} bestanden, "
          f"{len(fails)} Fehler, {len(warns)} Hinweise")
    for _, pruefung, info in fails:
        print(f"  ✗ {pruefung} — {info}")
    schreibe_summary(base_url)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
