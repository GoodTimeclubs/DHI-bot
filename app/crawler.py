"""Crawler für deutsches-hypnoseinstitut.de samt aller Subdomains.

Erfasst:
  1. Alle Seiten der Domains aus config.CRAWL_DOMAINS (Hauptdomain + 10
     Subdomains; per Sitemap, Fallback: Link-Crawl). Hoster-Platzhalterseiten
     noch unbefüllter Subdomains (z.B. legal.… bis zum Einstellen der neuen
     AGB) werden erkannt und übersprungen.
  2. Termine und Preise aller Angebote aus dem Website-Shop /seminare/
     (eingebettetes JSON, strukturiert; siehe parse_shop_html)

Ergebnis in DATA_DIR:
  pages.json    – [{url, title, text, source, fetched_at}]
  termine.json  – {seminars: [... inkl. preise ...], quelle, fetched_at}
  meta.json     – Crawl-Statistik

Aufruf:  python -m app.crawler [--from-fixtures]
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .config import (
    CRAWL_DOMAINS,
    DATA_DIR,
    FIXTURES_DIR,
    MAIN_DOMAIN,
    MAX_PAGES,
    REQUEST_DELAY,
)

SHOP_URL = f"https://{MAIN_DOMAIN}/seminare/"
HEADERS = {"User-Agent": "DHI-Bot/0.3 (Website-Assistent, Testbetrieb)"}

SKIP_PATTERNS = [
    re.compile(r"/old/"),
    re.compile(r"_PATCH_LOG"),
    re.compile(r"\.(?:jpg|jpeg|png|webp|gif|svg|ico|css|xml|txt|pdf|zip|mp[34])(?:\?|#|$)", re.I),
]


def _skip(url: str) -> bool:
    return any(p.search(url) for p in SKIP_PATTERNS)


def _norm(url: str) -> str:
    """URL normalisieren: Fragment + Query weg, www. vereinheitlichen.

    Query-Parameter tragen auf diesen statischen Seiten keinen eigenen Inhalt
    (praxen.…/?bereich=…&leistung=… liefert immer die Startseite, der
    Seminarkalender nur eine Filteransicht) — sie erzeugten im ersten
    Voll-Crawl ~60 inhaltsgleiche Duplikate. Die Kalender-JS-URL mit ?v=
    ist nicht betroffen (wird direkt geladen, ohne _norm).
    """
    url = url.split("#", 1)[0].strip()
    p = urlparse(url)
    host = p.netloc.lower().removeprefix("www.")
    path = p.path or "/"
    return f"https://{host}{path}"


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    try:
        r = client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        if r.status_code == 200:
            return r
        print(f"  ! {r.status_code} {url}")
    except Exception as e:  # noqa: BLE001
        print(f"  ! Fehler {type(e).__name__}: {url}")
    return None


# ── Platzhalter-Erkennung ────────────────────────────────────────────────────
# Noch unbefüllte Subdomains (z.B. legal.… bis zum Einstellen der neuen AGB)
# liefern die Default-Seite des Hosters mit Status 200 — solcher Inhalt darf
# nicht in den Index. Die Marker sind bewusst spezifisch gewählt, damit z.B.
# eine künftige Datenschutzerklärung, die den Hoster nur namentlich nennt,
# niemals fälschlich aussortiert wird.
PLACEHOLDER_TITLES = {"default page", "index of /"}
PLACEHOLDER_MARKERS = (
    "you are all set to go",
    "hpanel.hostinger.com",
    "this domain is parked",
    "website is under construction",
)


def is_placeholder_page(title: str, text: str) -> bool:
    t = (title or "").strip().lower()
    if t in PLACEHOLDER_TITLES:
        return True
    probe = f"{t}\n{(text or '')[:2000].lower()}"
    return any(m in probe for m in PLACEHOLDER_MARKERS)


# ── Sitemap ──────────────────────────────────────────────────────────────────

def sitemap_urls(client: httpx.Client, domain: str) -> list[str]:
    urls: list[str] = []
    todo = [f"https://{domain}/sitemap.xml"]
    seen = set()
    while todo:
        sm = todo.pop()
        if sm in seen:
            continue
        seen.add(sm)
        r = _get(client, sm)
        if r is None:
            continue
        raw = r.content
        if raw[:2] == b"\x1f\x8b":  # gzip-Datei
            try:
                raw = gzip.decompress(raw)
            except OSError:
                continue
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            continue
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in root.findall(".//sm:sitemap/sm:loc", ns):
            todo.append(loc.text.strip())
        for loc in root.findall(".//sm:url/sm:loc", ns):
            urls.append(_norm(loc.text.strip()))
    return urls


# ── HTML → Text ──────────────────────────────────────────────────────────────

def extract_page(url: str, html: str) -> tuple[dict, list[str]]:
    soup = BeautifulSoup(html, "lxml")
    links = [urljoin(url, a.get("href", "")) for a in soup.find_all("a")]
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else url
    desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = meta["content"].strip()
    text = soup.get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if desc and desc not in text:
        text = desc + "\n\n" + text
    return {"url": url, "title": title, "text": text}, links


# ── Termine & Preise aus dem Website-Shop (/seminare/) ───────────────────────
# Seit November 2026 verkauft das DHI nur noch über die eigene Website (Ablefy
# ist gekündigt, seminarkalender.html leitet in den Checkout um). Die Seite
# /seminare/ bettet alle Angebote als JSON ein (<script type="application/json"
# id="dhi-public-data…">): Termine, Orte, Buchungslink und die Preise für jede
# Zahlweise, auch für DHI-Vorausgebildete. Das ist die einzige Quelle für
# Termine und Preise — der Bot rechnet nie selbst.

_SHOP_DATA = re.compile(
    r'<script[^>]*\bid="dhi-public-data\d*"[^>]*>(.*?)</script>', re.S
)
# Die Shop-Software hängt Versionsnummern an Schlüssel („title223",
# „payment_options252"); die wechseln mit jedem Update und werden abgeschnitten.
_KEY_VERSION = re.compile(r"(?<=[a-z])\d+$")
# Zahlweisen in fester Reihenfolge, so wie der Shop sie anbietet
ZAHLWEISEN = ("regular", "instant", "rate4", "rate10")


def euro(cents: int) -> str:
    """359600 → „3.596,00 €" (deutsche Schreibweise wie auf der Website)."""
    return f"{cents / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _ohne_version(d: dict) -> dict:
    return {_KEY_VERSION.sub("", k): v for k, v in d.items()}


def _zahlweisen(opts: dict | None) -> dict:
    """Shop-Zahlweisen → {zahlweise: {gesamt, raten, label}} mit Euro-Strings."""
    out = {}
    for key in ZAHLWEISEN:
        o = (opts or {}).get(key)
        if not o or not o.get("total_cents"):
            continue
        out[key] = {
            "gesamt": euro(o["total_cents"]),
            "raten": _raten_text(o.get("rates") or []),
            "label": o.get("label", "").replace(" · ", ", "),
        }
    return out


def _raten_text(raten: list[int]) -> str:
    """[85405]*4 → „4 Raten à 854,05 €"; Rundungsrest in Rate 1 wird benannt."""
    if len(raten) < 2:
        return ""
    if len(set(raten)) == 1:
        return f"{len(raten)} Raten à {euro(raten[0])}"
    if len(set(raten[1:])) == 1:
        return f"{len(raten)} Raten (1. Rate {euro(raten[0])}, danach je {euro(raten[1])})"
    return f"{len(raten)} Raten: " + ", ".join(euro(r) for r in raten)


def parse_shop_html(html: str) -> dict:
    """Liest die eingebetteten Angebote aus /seminare/ → {seminars: [...]}.

    Jedes Angebot wird ein Termin-Eintrag im bisherigen Format (id, kind,
    stage, title, start, end, location, url) — plus „orte" (alle Orte des
    Angebots), „buchbar" und „preise". kind ist der Shop-Modus: presence
    (DHI 1.0 Vollpräsenz), hybrid (DHI 2.0 Live-Hybrid), online (DHI 3.0).
    """
    m = _SHOP_DATA.search(html or "")
    if not m:
        return {"seminars": []}
    seminars = []
    for raw in json.loads(m.group(1)):
        o = _ohne_version(raw)
        if not o.get("starts_on") or not o.get("mode"):
            continue
        orte = list((o.get("locations") or {}).keys()) or ["Online"]
        seminars.append({
            "id": str(o.get("id", "")),
            "kind": o["mode"],
            "stage": o.get("sales_scope") or o.get("stage", ""),
            "title": o.get("title", ""),
            "start": o["starts_on"],
            "end": o.get("ends_on") or o["starts_on"],
            "location": " / ".join(orte),
            "orte": orte,
            "url": o.get("detail_url", ""),
            "buchbar": bool(o.get("bookable", True)),
            "preise": {
                "regulaer": _zahlweisen(o.get("payment_options")),
                "vorausgebildet": _zahlweisen(o.get("preeducated_options")),
            },
        })
    seminars.sort(key=lambda s: (s["start"], s["id"]))
    return {"seminars": seminars}


def fetch_shop(client: httpx.Client) -> dict:
    """Lädt /seminare/ und parst die eingebetteten Angebote."""
    r = _get(client, SHOP_URL)
    if r is None:
        return {"seminars": []}
    data = parse_shop_html(r.text)
    if not data["seminars"]:
        print("  ! Keine Angebotsdaten (dhi-public-data) in /seminare/ gefunden")
    data["quelle"] = SHOP_URL
    return data


# ── Haupt-Crawl ──────────────────────────────────────────────────────────────

def crawl_pages(client: httpx.Client) -> tuple[list[dict], dict]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    domains = set(CRAWL_DOMAINS)
    queue: list[str] = []
    for d in CRAWL_DOMAINS:
        found = sitemap_urls(client, d)
        print(f"Sitemap {d}: {len(found)} URLs")
        queue += found or [f"https://{d}/"]

    pages: list[dict] = []
    seen: set[str] = set()
    seen_text: set[int] = set()  # Inhalts-Duplikate (/index.html-Zwillinge, Soft-404s)
    i = 0
    while i < len(queue) and len(pages) < MAX_PAGES:
        url = _norm(queue[i])
        i += 1
        host = urlparse(url).netloc
        if url in seen or _skip(url) or host not in domains:
            continue
        seen.add(url)
        r = _get(client, url)
        time.sleep(REQUEST_DELAY)
        if r is None or "text/html" not in r.headers.get("content-type", "text/html"):
            continue
        page, links = extract_page(url, r.text)
        if is_placeholder_page(page["title"], page["text"]):
            print(f"  ~ Platzhalter übersprungen (Domain noch unbefüllt): {url}")
            continue
        th = hash(page["text"])
        if th in seen_text:
            print(f"  ~ Duplikat übersprungen (Inhalt bereits erfasst): {url}")
            continue
        seen_text.add(th)
        page.update(source="website", fetched_at=now)
        pages.append(page)
        print(f"  ✓ {url} ({len(page['text'])} Zeichen)")
        # Fallback-Linkcrawl (falls Sitemap unvollständig)
        for link in links:
            n = _norm(link) if link.startswith(("http", "/")) else ""
            if n and urlparse(n).netloc in domains and n not in seen and not _skip(n):
                queue.append(n)

    if len(pages) >= MAX_PAGES:
        rest = {u for u in (_norm(q) for q in queue[i:]) if u not in seen and not _skip(u)}
        if rest:
            print(f"  ! Seitenlimit MAX_PAGES={MAX_PAGES} erreicht — {len(rest)} URLs nicht geholt")

    try:
        kalender = fetch_shop(client)
    except Exception as e:  # noqa: BLE001
        # Nächtlicher Lauf: ein Umbau der Shop-Seite darf nicht den Index kosten.
        print(f"  ! Shop-Daten nicht auswertbar ({type(e).__name__}: {e})")
        kalender = {"seminars": []}
    print(f"Shop: {len(kalender['seminars'])} Angebote")
    kalender["fetched_at"] = now
    return pages, kalender


def load_fixtures() -> tuple[list[dict], dict]:
    """Offline-Modus: nutzt gespeicherte Fixtures statt Live-Crawl (für Tests).

    Format der Seiten-Fixtures (fixtures/pages/*.txt):
      Zeile 1: URL, Zeile 2: Titel, danach Leerzeile und der Seitentext.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pages = []
    for f in sorted((FIXTURES_DIR / "pages").glob("*.txt")):
        raw = f.read_text(encoding="utf-8")
        head, _, body = raw.partition("\n\n")
        lines = head.splitlines()
        url = lines[0].strip()
        title = lines[1].strip() if len(lines) > 1 else url
        pages.append({
            "url": url,
            "title": title,
            "text": body.strip(),
            "source": "website",
            "fetched_at": now,
        })
    kalender = parse_shop_html((FIXTURES_DIR / "seminare.html").read_text(encoding="utf-8"))
    kalender["quelle"] = "fixtures/seminare.html"
    kalender["fetched_at"] = now
    return pages, kalender


def run(from_fixtures: bool = False) -> dict:
    print(f"=== Crawl gestartet ({'Fixtures' if from_fixtures else 'Live'}) ===")
    if from_fixtures:
        pages, kalender = load_fixtures()
    else:
        with httpx.Client() as client:
            pages, kalender = crawl_pages(client)

    if not pages:
        raise RuntimeError("Crawl ergab 0 Seiten — Abbruch, bestehende Daten bleiben erhalten.")

    (DATA_DIR / "pages.json").write_text(
        json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    termine_path = DATA_DIR / "termine.json"
    if kalender.get("seminars") or not termine_path.exists():
        termine_path.write_text(json.dumps(kalender, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        # Lieber gestrige Termine und Preise als gar keine: ohne sie fehlen dem
        # Bot sämtliche Preisdaten.
        print("  ! 0 Angebote — termine.json vom letzten erfolgreichen Lauf bleibt erhalten")
    pro_domain: dict[str, int] = {}
    for p in pages:
        host = urlparse(p["url"]).netloc
        pro_domain[host] = pro_domain.get(host, 0) + 1
    meta = {
        "pages": len(pages),
        "termine": len(kalender.get("seminars", [])),
        "mode": "fixtures" if from_fixtures else "live",
        "pages_pro_domain": dict(sorted(pro_domain.items())),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (DATA_DIR / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"=== Fertig: {meta['pages']} Seiten, {meta['termine']} Termine ===")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-fixtures", action="store_true", help="Fixtures statt Live-Crawl nutzen")
    args = ap.parse_args()
    run(from_fixtures=args.from_fixtures)
