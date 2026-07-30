#!/usr/bin/env python3
"""Testkatalog-Runner: spielt tests/testkatalog.yaml gegen einen laufenden
DHI-Bot durch und prüft jede Antwort automatisch (plus Bericht für die
manuelle Durchsicht).

Aufruf (Server muss laufen, für >20 Fragen mit TRUST_PROXY=1 starten):
    python tests/run_testkatalog.py --base-url http://127.0.0.1:8000

Optionen:
    --only A1,C6      nur bestimmte Fall-IDs (Präfix-Match)
    --workers 4       parallele Anfragen
    --no-xff          keine X-Forwarded-For-Rotation (dann greift das
                      Rate-Limit von 20 Anfragen / 5 Min pro IP!)
    --out PREFIX      Berichtspfade (Default tests/report/<Zeitstempel>)

Exit-Code 0 = alle harten Checks bestanden, 1 = mindestens ein FAIL.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

# ── Textwerkzeuge ────────────────────────────────────────────────────────────

MD_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")


def strip_links(text: str) -> tuple[str, list[str]]:
    """Ersetzt [Label](URL) durch Label und liefert die Link-URLs zurück."""
    urls = [m.group(2) for m in MD_LINK.finditer(text)]
    return MD_LINK.sub(r"\1", text), urls


def wortzahl(text: str) -> int:
    plain, _ = strip_links(text)
    return len(plain.split())


# ── Globale Checks (gelten für jede Antwort) ────────────────────────────────

DU_RE = re.compile(r"\b(du|dich|dir|dein\w*|euch|euer\w*|eure\w*)\b", re.I)


def check_global(reply: str, cfg: dict) -> list[dict]:
    out = []
    plain, _ = strip_links(reply)
    plain_wo_urls = re.sub(r"https?://\S+", "", plain)

    if cfg.get("sie_form"):
        m = DU_RE.search(plain_wo_urls)
        out.append({"check": "global:sie_form", "ok": m is None,
                    "info": f"Du-Form gefunden: „{m.group(0)}“" if m else "Sie-Form eingehalten"})
    if cfg.get("kein_markdown"):
        # Spec v0.2.2: sparsames **fett** ist erlaubt (Widget rendert es als <b>);
        # verboten bleiben #-Überschriften, Tabellen und *kursiv*.
        heading = re.search(r"(?m)^\s{0,3}#{1,6}\s", reply)
        tabelle = re.search(r"(?m)^\s*\|.*\|\s*$", reply)
        fett = len(re.findall(r"\*\*[^*\n]+\*\*", reply))
        rest_f = re.sub(r"\*\*[^*\n]+\*\*", "", reply)
        kursiv = re.search(r"(?<!\*)\*[^*\s][^*\n]*\*(?!\*)", rest_f)
        bad = bool(heading or tabelle or kursiv)
        out.append({"check": "global:kein_markdown", "ok": not bad,
                    "soft_warn": bool(not bad and fett > 3),
                    "info": ("#-Überschrift" if heading else "Tabelle" if tabelle
                             else "*kursiv*" if kursiv else f"ok ({fett}× fett)")})
    if cfg.get("keine_nackte_url"):
        rest = MD_LINK.sub("", reply)
        naked = re.search(r"https?://\S+", rest)
        out.append({"check": "global:keine_nackte_url", "ok": naked is None,
                    "info": f"nackte URL: {naked.group(0)[:60]}" if naked else "ok"})
    if cfg.get("kontakt_links"):
        probleme = []
        for u in re.findall(r"\]\(((?:tel|mailto):[^)]*)\)", reply):
            probleme.append(f"nicht darstellbarer Link (Widget rendert nur https): {u[:40]}")
        for m in re.finditer(r"wa\.me/(\+?\d+)", reply):
            if m.group(1).lstrip("+") != "4915154434470":
                probleme.append(f"falsche WhatsApp-Nummer: wa.me/{m.group(1)}")
        out.append({"check": "global:kontakt_links", "ok": not probleme,
                    "info": "; ".join(probleme) if probleme else "ok"})
    maxw = int(cfg.get("max_woerter", 0) or 0)
    if maxw:
        n = wortzahl(reply)
        warn = int(cfg.get("warn_woerter", 0) or 0)
        ok = n <= maxw
        out.append({"check": "global:laenge", "ok": ok,
                    "soft_warn": bool(ok and warn and n > warn),
                    "info": f"{n} Wörter (Limit {maxw}, Warnschwelle {warn})"})
    return out


# ── Fall-Checks ─────────────────────────────────────────────────────────────

def _search_any(patterns: list[str], text: str) -> str | None:
    for p in patterns:
        if re.search(p, text, re.I):
            return p
    return None


def next_termine(termine: dict, spec: dict, today: str) -> list[dict]:
    """Die nächsten passenden Termine laut Filter (kind/stage/location als Regex)."""
    res = []
    for s in termine.get("seminars", []):
        if s.get("start", "") < today:
            continue
        ok = True
        for key in ("kind", "stage", "location"):
            want = spec.get(key)
            if want is None:
                continue
            optionen = [w.strip().lower() for w in str(want).split("|")]
            if str(s.get(key, "")).lower() not in optionen:
                ok = False
        if ok:
            res.append(s)
    res.sort(key=lambda s: s["start"])
    return res[: int(spec.get("top", 2))]


def datum_varianten(iso: str) -> list[str]:
    """Regex-Varianten für ein Startdatum — deckt auch Bereichsschreibweisen
    wie „21.–25. September 2026" oder „21.09.–25.09." ab."""
    d = datetime.fromisoformat(iso)
    monat = MONATE[d.month - 1]
    return [
        rf"{d.day:02d}\.{d.month:02d}\.{d.year}",                     # 21.09.2026
        rf"\b{d.day}\.{d.month}\.{d.year}",                           # 21.9.2026
        rf"\b{d.day}\.\s*(?:[–—-]\s*\d{{1,2}}\.\s*)?{monat}",         # 21. September / 21.–25. September
        rf"{d.day:02d}\.{d.month:02d}\.(?!\d)",                       # 21.09. (ohne Jahr)
    ]


def check_fall(fall: dict, reply: str, urls: list[str], termine: dict) -> list[dict]:
    out = []
    checks = fall.get("checks") or {}
    for key, val in checks.items():
        if key == "must_all":
            for p in val:
                ok = re.search(p, reply, re.I) is not None
                out.append({"check": f"must_all:{p}", "ok": ok,
                            "info": "gefunden" if ok else "fehlt"})
        elif key.startswith("must_any"):
            hit = _search_any(val, reply)
            out.append({"check": f"{key}:{'|'.join(val)[:60]}", "ok": hit is not None,
                        "info": f"Treffer: {hit}" if hit else "keiner der Ausdrücke gefunden"})
        elif key == "must_not":
            for p in val:
                m = re.search(p, reply, re.I)
                out.append({"check": f"must_not:{p}", "ok": m is None,
                            "info": f"VERBOTEN gefunden: „{m.group(0)[:50]}“" if m else "ok"})
        elif key == "link_any":
            ok = any(sub in u for u in urls for sub in val)
            out.append({"check": f"link_any:{'|'.join(val)}", "ok": ok,
                        "info": f"Links: {urls}" if urls else "keine [Label](URL)-Links in der Antwort"})
        elif key == "next_termin":
            today = date.today().isoformat()
            kandidaten = next_termine(termine, val, today)
            if not kandidaten:
                out.append({"check": "next_termin", "ok": False,
                            "info": f"kein passender Termin in termine.json für Filter {val}"})
                continue
            varianten = [v for k in kandidaten for v in datum_varianten(k["start"])]
            hit = next((v for v in varianten if re.search(v, reply)), None)
            ok = hit is not None
            soft = bool(val.get("soft"))
            out.append({"check": f"next_termin:{ {k: v for k, v in val.items() if k not in ('top', 'soft')} }",
                        "ok": ok or soft, "soft_warn": (not ok) and soft,
                        "info": f"Datum {hit} gefunden" if ok else
                        f"keines der erwarteten Daten genannt (erwartet z.B. {kandidaten[0]['start']})"})
        elif key == "if_mentions":
            trig = re.search(val["trigger"], reply, re.I)
            if trig:
                hit = _search_any(val["then_must_any"], reply)
                out.append({"check": f"if_mentions:{val['trigger']}", "ok": hit is not None,
                            "info": f"„{trig.group(0)}“ genannt, Kontext-Begriff: {hit or 'FEHLT'}"})
            else:
                out.append({"check": f"if_mentions:{val['trigger']}", "ok": True,
                            "info": "Trigger nicht genannt — Check entfällt"})
    return out


# ── Anfrage ─────────────────────────────────────────────────────────────────

def ask(base_url: str, frage: str, xff: str | None, timeout: float = 90) -> dict:
    headers = {"X-Forwarded-For": xff} if xff else {}
    last_err = None
    for versuch in (1, 2):
        try:
            r = httpx.post(f"{base_url}/api/chat", json={"message": frage, "history": []},
                           headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(3 * versuch)
    return {"error": last_err}


# ── Hauptlauf ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--katalog", default=str(ROOT / "tests" / "testkatalog.yaml"))
    ap.add_argument("--termine", default=str(ROOT / "data" / "termine.json"))
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-xff", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    kat = yaml.safe_load(Path(args.katalog).read_text(encoding="utf-8"))
    termine = json.loads(Path(args.termine).read_text(encoding="utf-8"))
    faelle = kat["faelle"]
    if args.only:
        pref = [p.strip().lower() for p in args.only.split(",") if p.strip()]
        faelle = [f for f in faelle if any(f["id"].lower().startswith(p) for p in pref)]
    gcfg = kat.get("global_checks", {})

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_prefix = Path(args.out) if args.out else ROOT / "tests" / "report" / stamp
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    print(f"Testkatalog: {len(faelle)} Fälle gegen {args.base_url}")
    health = httpx.get(f"{args.base_url}/api/health", timeout=15).json()
    print(f"Server: model={health.get('model')} mock={health.get('mock_mode')} "
          f"chunks={health.get('chunks')} termine={health.get('termine')}")
    if health.get("mock_mode"):
        print("!! ACHTUNG: Server läuft im Mock-Modus — Antwortqualität wird NICHT geprüft.")

    def run_one(i_fall):
        i, fall = i_fall
        xff = None if args.no_xff else f"203.0.113.{(i % 200) + 1}"
        t0 = time.time()
        resp = ask(args.base_url, fall["frage"], xff)
        dauer = time.time() - t0
        if "error" in resp:
            return {**fall, "reply": "", "sources": [], "dauer_s": round(dauer, 1),
                    "results": [{"check": "request", "ok": False, "info": resp["error"]}]}
        reply = resp.get("reply", "")
        _, urls = strip_links(reply)
        results = check_global(reply, gcfg) + check_fall(fall, reply, urls, termine)
        return {**fall, "reply": reply, "sources": resp.get("sources", []),
                "mock": resp.get("mock"), "dauer_s": round(dauer, 1), "results": results}

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        ergebnisse = list(ex.map(run_one, enumerate(faelle)))

    # ── Auswertung & Berichte ───────────────────────────────────────────────
    n_fail = 0
    zeilen = []
    for e in ergebnisse:
        fails = [r for r in e["results"] if not r["ok"]]
        warns = [r for r in e["results"] if r.get("soft_warn")]
        status = "FAIL" if fails else ("WARN" if warns else "PASS")
        n_fail += bool(fails)
        zeilen.append((e["id"], status, len(fails), len(warns), wortzahl(e["reply"]), e["dauer_s"]))
        print(f"  {status:4} {e['id']:32} ({len(fails)} Fehler, {len(warns)} Warnungen, "
              f"{wortzahl(e['reply'])} Wörter, {e['dauer_s']}s)")
        for r in fails:
            print(f"        ✗ {r['check']} — {r['info']}")

    with open(f"{out_prefix}.jsonl", "w", encoding="utf-8") as f:
        for e in ergebnisse:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    md = [f"# DHI Bot — Testkatalog-Lauf {stamp}", "",
          f"Server: `{args.base_url}` · Modell: `{health.get('model')}` · "
          f"Mock: {health.get('mock_mode')} · Chunks: {health.get('chunks')} · "
          f"Termine: {health.get('termine')}", "",
          f"**Ergebnis: {len(ergebnisse) - n_fail}/{len(ergebnisse)} bestanden**", "",
          "| Fall | Status | Fehler | Warnungen | Wörter | Dauer |", "|---|---|---|---|---|---|"]
    for z in zeilen:
        md.append(f"| {z[0]} | {z[1]} | {z[2]} | {z[3]} | {z[4]} | {z[5]}s |")
    md.append("")
    for e in ergebnisse:
        fails = [r for r in e["results"] if not r["ok"]]
        md += [f"## {e['id']} — {'FAIL' if fails else 'PASS'}", "",
               f"**Frage:** {e['frage']}", "",
               f"**Soll:** {e.get('soll', '').strip()}", "",
               "**Antwort:**", "", "> " + e["reply"].replace("\n", "\n> "), ""]
        md.append("**Checks:**")
        md.append("")
        for r in e["results"]:
            sym = "✅" if r["ok"] and not r.get("soft_warn") else ("⚠️" if r.get("soft_warn") else "❌")
            md.append(f"- {sym} `{r['check']}` — {r['info']}")
        md.append("")
    Path(f"{out_prefix}.md").write_text("\n".join(md), encoding="utf-8")

    print(f"\nBerichte: {out_prefix}.md / .jsonl")
    print(f"Gesamt: {len(ergebnisse) - n_fail}/{len(ergebnisse)} bestanden")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
