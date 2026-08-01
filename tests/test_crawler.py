"""Unit-Tests für Crawl-Konfiguration, Platzhalter-Filter und Sitemap-Parsing (v0.3.0).

Absichert die Domain-Erweiterung: alle 11 DHI-Domains stehen im Standard-Crawl,
CRAWL_DOMAINS bleibt per .env überschreibbar, Hoster-Platzhalterseiten
(z.B. legal.… vor dem Einstellen der neuen AGB) landen nie im Index —
künftige echte legal-Inhalte (AGB/Datenschutz) aber sehr wohl.

Läuft ohne Server, ohne API-Key und ohne Internet:
    pytest tests/test_crawler.py -v
"""
from __future__ import annotations

import gzip
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import (  # noqa: E402
    _DEFAULT_CRAWL_DOMAINS,
    CRAWL_DOMAINS,
    MAIN_DOMAIN,
    parse_domain_list,
)
from app.crawler import (  # noqa: E402
    _norm,
    is_placeholder_page,
    load_fixtures,
    sitemap_urls,
)

ERWARTETE_DOMAINS = [
    "deutsches-hypnoseinstitut.de",
    "lars.deutsches-hypnoseinstitut.de",
    "nautilus-code.deutsches-hypnoseinstitut.de",
    "hypnospathie.deutsches-hypnoseinstitut.de",
    "hypnosepraxis-aschaffenburg.deutsches-hypnoseinstitut.de",
    "hypnosepraxis-berlin.deutsches-hypnoseinstitut.de",
    "hypnosepraxis-oberstaufen.deutsches-hypnoseinstitut.de",
    "praxen.deutsches-hypnoseinstitut.de",
    "hybrid.deutsches-hypnoseinstitut.de",
    "experte.deutsches-hypnoseinstitut.de",
    "legal.deutsches-hypnoseinstitut.de",
]


# ── Domain-Konfiguration ─────────────────────────────────────────────────────

def test_standard_liste_umfasst_alle_11_domains():
    standard = parse_domain_list(_DEFAULT_CRAWL_DOMAINS)
    assert standard == ERWARTETE_DOMAINS
    assert standard[0] == MAIN_DOMAIN  # Hauptdomain zuerst (Crawl-Priorität)


def test_aktive_konfiguration_nutzt_standard_ohne_override():
    if "CRAWL_DOMAINS" not in os.environ:  # .env kann bewusst abweichen
        assert CRAWL_DOMAINS == ERWARTETE_DOMAINS


def test_domainliste_per_env_ueberschreibbar():
    raw = (" Deutsches-Hypnoseinstitut.de , https://www.hybrid.deutsches-hypnoseinstitut.de/ ,"
           ", http://legal.deutsches-hypnoseinstitut.de/agb.html ")
    assert parse_domain_list(raw) == [
        "deutsches-hypnoseinstitut.de",
        "hybrid.deutsches-hypnoseinstitut.de",
        "legal.deutsches-hypnoseinstitut.de",
    ]


def test_norm_behandelt_subdomains_und_www():
    assert _norm("https://www.lars.deutsches-hypnoseinstitut.de/vita.html#abschnitt") == (
        "https://lars.deutsches-hypnoseinstitut.de/vita.html"
    )
    # Query-Parameter tragen auf diesen statischen Seiten keinen Inhalt und
    # erzeugten im ersten Voll-Crawl ~60 Duplikate (praxen.…/?bereich=…).
    assert _norm("https://praxen.deutsches-hypnoseinstitut.de/?bereich=coaching&leistung=x") == (
        "https://praxen.deutsches-hypnoseinstitut.de/"
    )


# ── Platzhalter-Filter (legal.… liefert bis zum Befüllen Hostinger-Default) ──

def test_hostinger_default_seite_wird_erkannt():
    assert is_placeholder_page(
        "Default page",
        "You Are All Set to Go!\nUpload your website files or install WordPress …",
    )
    assert is_placeholder_page("Willkommen", "… You are all set to go! Upload files …")
    assert is_placeholder_page("Bald verfügbar", "This domain is parked free of charge.")


def test_echte_inhalte_bleiben_erhalten():
    startseite = (ROOT / "fixtures" / "pages" / "01-startseite.txt").read_text(encoding="utf-8")
    assert not is_placeholder_page("Hypnose fundiert lernen | DHI", startseite)
    # Entscheidend: Künftige AGB/Datenschutz auf legal.… dürfen den Hoster
    # NAMENTLICH nennen, ohne aussortiert zu werden.
    agb = ("Allgemeine Geschäftsbedingungen des Deutschen Hypnoseinstituts. "
           "§1 Geltungsbereich … Unsere Website wird bei Hostinger International Ltd. gehostet.")
    assert not is_placeholder_page("AGB | Deutsches Hypnoseinstitut", agb)


# ── Sitemap-Parsing (inkl. Sitemap-Index und gzip, ohne Netz) ────────────────

class _Resp:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.headers = {}
        try:
            self.text = content.decode("utf-8")
        except UnicodeDecodeError:
            self.text = ""


class _Client:
    """Mini-Ersatz für httpx.Client — beantwortet nur vorbereitete URLs."""

    def __init__(self, mapping: dict[str, bytes]):
        self.mapping = mapping

    def get(self, url: str, **_kw):
        if url in self.mapping:
            return _Resp(self.mapping[url])
        return _Resp(b"not found", 404)


_SM = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def test_sitemap_index_und_gzip_werden_aufgeloest():
    d = "lars.deutsches-hypnoseinstitut.de"
    index_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex {_SM}>
 <sitemap><loc>https://{d}/sitemap-seiten.xml</loc></sitemap>
 <sitemap><loc>https://{d}/sitemap-extra.xml.gz</loc></sitemap>
</sitemapindex>"""
    seiten_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset {_SM}>
 <url><loc>https://{d}/</loc></url>
 <url><loc>https://www.{d}/vita.html#x</loc></url>
</urlset>"""
    extra_xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
                 f'<urlset {_SM}><url><loc>https://{d}/kontakt.html</loc></url></urlset>')
    client = _Client({
        f"https://{d}/sitemap.xml": index_xml.encode(),
        f"https://{d}/sitemap-seiten.xml": seiten_xml.encode(),
        f"https://{d}/sitemap-extra.xml.gz": gzip.compress(extra_xml.encode()),
    })
    urls = sitemap_urls(client, d)
    assert set(urls) == {
        f"https://{d}/",
        f"https://{d}/vita.html",
        f"https://{d}/kontakt.html",
    }


def test_fehlende_sitemap_liefert_leere_liste():
    urls = sitemap_urls(_Client({}), "legal.deutsches-hypnoseinstitut.de")
    assert urls == []  # crawl_pages fällt dann auf die Startseite der Domain zurück


# ── Fixtures decken die neuen Subdomains ab ──────────────────────────────────

def test_crawl_ueberspringt_inhaltsgleiche_duplikate(monkeypatch):
    """Soft-404s, /index.html-Zwillinge und Query-Varianten dürfen den Index
    nicht aufblähen (Befund aus dem ersten Voll-Crawl am 01.08.: 581 Seiten,
    davon ~80 inhaltsgleiche Duplikate)."""
    import app.crawler as cr
    monkeypatch.setattr(cr, "REQUEST_DELAY", 0)
    d = "deutsches-hypnoseinstitut.de"
    html = ("<html><head><title>Testseite</title></head><body><p>"
            + "Echter Inhalt mit genug Text. " * 20 + "</p></body></html>").encode()
    sm = (f'<?xml version="1.0" encoding="UTF-8"?><urlset {_SM}>'
          f'<url><loc>https://{d}/a.html</loc></url>'
          f'<url><loc>https://{d}/a.html?variante=1</loc></url>'
          f'<url><loc>https://{d}/b.html</loc></url>'
          f'</urlset>')
    client = _Client({
        f"https://{d}/sitemap.xml": sm.encode(),
        f"https://{d}/a.html": html,
        f"https://{d}/b.html": html,  # inhaltsgleich zu a.html → Duplikat
    })
    pages, _kalender = cr.crawl_pages(client)
    assert [p["url"] for p in pages] == [f"https://{d}/a.html"]


def test_fixtures_enthalten_subdomain_seiten():
    pages, kalender = load_fixtures()
    hosts = {p["url"].split("/")[2] for p in pages}
    assert "lars.deutsches-hypnoseinstitut.de" in hosts
    assert "praxen.deutsches-hypnoseinstitut.de" in hosts
    assert "hypnosepraxis-berlin.deutsches-hypnoseinstitut.de" in hosts
    assert all(p["text"] for p in pages)
    assert kalender.get("seminars")
