"""Crawler für deutsches-hypnoseinstitut.de samt aller Subdomains.

Erfasst:
  1. Alle Seiten der Domains aus config.CRAWL_DOMAINS (Hauptdomain + 10
     Subdomains; per Sitemap, Fallback: Link-Crawl). Hoster-Platzhalterseiten
     noch unbefüllter Subdomains (z.B. legal.… bis zum Einstellen der neuen
     AGB) werden erkannt und übersprungen.
  2. Die Termindaten aus assets/js/dhi-seminarkalender.js (strukturiert)
  3. Die Ablefy-Buchungsseiten auf dhi2.de (Preise, Raten, Restplätze)

Ergebnis in DATA_DIR:
  pages.json    – [{url, title, text, source, fetched_at}]
  termine.json  – {seminars: [...], products: {...}, notes: [...], js_url, fetched_at}
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

KALENDER_PAGE = f"https://{MAIN_DOMAIN}/seminarkalender.html"
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


# ── Seminarkalender-JS ───────────────────────────────────────────────────────

def _bracket_block(s: str, start: int, open_ch: str, close_ch: str) -> str:
    depth = 0
    for i in range(start, len(s)):
        if s[i] == open_ch:
            depth += 1
        elif s[i] == close_ch:
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return ""


def parse_kalender_js(js: str) -> dict:
    """Parst PRODUCT-Map, seminars-Array und notes aus dhi-seminarkalender.js."""
    products: dict[str, str] = {}
    m = re.search(r"PRODUCT\s*=\s*\{", js)
    if m:
        block = _bracket_block(js, m.end() - 1, "{", "}")
        for k, v in re.findall(r"(\w+)\s*:\s*[\"']([^\"']+)[\"']", block):
            products[k] = v

    seminars: list[dict] = []
    m = re.search(r"seminars\s*=\s*\[", js)
    if m:
        block = _bracket_block(js, m.end() - 1, "[", "]")
        for entry in re.finditer(r"\{[^{}]*\}", block):
            body = entry.group(0)
            item: dict = {}
            for key in ("id", "kind", "stage", "title", "start", "end", "time", "location"):
                km = re.search(rf"\b{key}\s*:\s*[\"']([^\"']*)[\"']", body)
                if km:
                    item[key] = km.group(1)
            um = re.search(r"\burl\s*:\s*(?:PRODUCT\.(\w+)|[\"']([^\"']+)[\"'])", body)
            if um:
                item["url"] = products.get(um.group(1), "") if um.group(1) else um.group(2)
                if um.group(1):
                    item["product_key"] = um.group(1)
            if item.get("start"):
                seminars.append(item)

    notes: list[str] = []
    m = re.search(r"notes\s*=\s*\[", js)
    if m:
        block = _bracket_block(js, m.end() - 1, "[", "]")
        notes = [s for s in re.findall(r"[\"']([^\"']{10,})[\"']", block)]

    seminars.sort(key=lambda x: x.get("start", ""))
    return {"products": products, "seminars": seminars, "notes": notes}


def fetch_kalender(client: httpx.Client) -> dict:
    """Lädt seminarkalender.html, findet die aktuelle JS-URL und parst sie."""
    r = _get(client, KALENDER_PAGE)
    if r is None:
        return {}
    m = re.search(r"[\"']([^\"']*dhi-seminarkalender\.js[^\"']*)[\"']", r.text)
    if not m:
        print("  ! Kalender-Script nicht in seminarkalender.html gefunden")
        return {}
    js_url = urljoin(KALENDER_PAGE, m.group(1))
    rj = _get(client, js_url)
    if rj is None:
        return {}
    data = parse_kalender_js(rj.text)
    data["js_url"] = js_url
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

    kalender = fetch_kalender(client)
    if kalender.get("seminars"):
        print(f"Kalender: {len(kalender['seminars'])} Termine, {len(kalender.get('products', {}))} Produkte")

    # Ablefy-Buchungsseiten (dhi2.de) mitcrawlen
    for key, purl in (kalender.get("products") or {}).items():
        r = _get(client, purl)
        time.sleep(REQUEST_DELAY)
        if r is None:
            continue
        page, _ = extract_page(purl, r.text)
        page.update(source="buchungsseite", product_key=key, fetched_at=now)
        pages.append(page)
        print(f"  ✓ [Buchung/{key}] {purl}")

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
        pages.append(
            {
                "url": url,
                "title": title,
                "text": body.strip(),
                "source": "buchungsseite" if "dhi2.de" in url else "website",
                "fetched_at": now,
            }
        )
    js = (FIXTURES_DIR / "dhi-seminarkalender.js").read_text(encoding="utf-8")
    kalender = parse_kalender_js(js)
    kalender["js_url"] = "fixtures/dhi-seminarkalender.js"
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
    (DATA_DIR / "termine.json").write_text(
        json.dumps(kalender, ensure_ascii=False, indent=1), encoding="utf-8"
    )
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
