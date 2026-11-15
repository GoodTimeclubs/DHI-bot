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
    euro,
    load_fixtures,
    parse_shop_html,
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


# ── Termine & Preise aus dem Website-Shop (/seminare/, ab Nov. 2026) ─────────

SHOP_HTML = (ROOT / "fixtures" / "seminare.html").read_text(encoding="utf-8")


def _shop_html(*angebote) -> str:
    import json
    return ('<html><script type="application/json" id="dhi-public-data999">'
            + json.dumps(list(angebote)) + "</script></html>")


def _angebot(**extra) -> dict:
    o = {
        "id": 1, "mode": "presence", "stage": "1+2", "sales_scope238": "1+2",
        "starts_on238": "2027-01-11", "ends_on238": "2027-01-15",
        "locations238": {"Aschaffenburg": "Aschaffenburg"},
        "detail_url": "https://deutsches-hypnoseinstitut.de/seminare/1/",
        "title223": "11.01.2027 · DHI 1.0 · Vollpräsenz · Stufe 1+2",
        "bookable252": True,
        "payment_options252": {
            "regular": {"total_cents": 359600, "rates": [359600], "label": "Regelpreis"},
            "rate4": {"total_cents": 341620, "rates": [85405] * 4, "label": "4 Raten · 5 % Finanzvorteil"},
        },
        "preeducated_options252": {
            "rate4": {"total_cents": 304042, "rates": [76012, 76010, 76010, 76010], "label": "4 Raten"},
        },
    }
    o.update(extra)
    return o


def test_euro_schreibweise():
    assert euro(359600) == "3.596,00 €"
    assert euro(85405) == "854,05 €"
    assert euro(650000) == "6.500,00 €"


def test_shop_angebot_wird_termin_mit_preisen():
    s = parse_shop_html(_shop_html(_angebot()))["seminars"][0]
    assert (s["kind"], s["stage"], s["start"], s["end"]) == ("presence", "1+2", "2027-01-11", "2027-01-15")
    assert s["location"] == "Aschaffenburg" and s["buchbar"] is True
    assert s["url"] == "https://deutsches-hypnoseinstitut.de/seminare/1/"
    assert s["preise"]["regulaer"]["regular"]["gesamt"] == "3.596,00 €"
    assert s["preise"]["regulaer"]["rate4"]["raten"] == "4 Raten à 854,05 €"
    assert s["preise"]["regulaer"]["rate4"]["label"] == "4 Raten, 5 % Finanzvorteil"


def test_ungleiche_raten_werden_nicht_als_gleich_ausgegeben():
    """76012 + 3 × 76010: „à 760,12 €" wäre für drei der vier Raten falsch."""
    s = parse_shop_html(_shop_html(_angebot()))["seminars"][0]
    assert s["preise"]["vorausgebildet"]["rate4"]["raten"] == (
        "4 Raten (1. Rate 760,12 €, danach je 760,10 €)")


def test_hybrid_hat_mehrere_orte_und_online_ohne_ort_heisst_online():
    hybrid = _angebot(id=2, mode="hybrid", locations238={"Aschaffenburg": "x", "Leipzig": "y"})
    online = _angebot(id=3, mode="online", locations238={})
    s = {x["id"]: x for x in parse_shop_html(_shop_html(hybrid, online))["seminars"]}
    assert s["2"]["orte"] == ["Aschaffenburg", "Leipzig"]
    assert s["2"]["location"] == "Aschaffenburg / Leipzig"
    assert s["3"]["orte"] == ["Online"]


def test_nicht_buchbares_angebot_bleibt_als_anfrage_erhalten():
    s = parse_shop_html(_shop_html(_angebot(bookable252=False)))["seminars"][0]
    assert s["buchbar"] is False


def test_shop_ohne_datenblock_liefert_keine_termine():
    assert parse_shop_html("<html>umgebaut</html>") == {"seminars": []}


def test_fixture_enthaelt_alle_drei_formate_zum_gleichen_preis():
    """Lars, 05.11.2026: alle drei Varianten kosten jetzt denselben Betrag."""
    seminars = parse_shop_html(SHOP_HTML)["seminars"]
    assert {s["kind"] for s in seminars} == {"presence", "hybrid", "online"}
    preise_12 = {s["preise"]["regulaer"]["regular"]["gesamt"] for s in seminars if s["stage"] == "1+2"}
    assert preise_12 == {"3.596,00 €"}
    vorausgebildet = {s["preise"]["vorausgebildet"]["regular"]["gesamt"] for s in seminars if s["stage"] == "1+2"}
    assert vorausgebildet == {"3.200,44 €"}  # 11 % Rabatt laut Shop


def test_leerer_shop_ueberschreibt_vorhandene_termine_nicht(monkeypatch, tmp_path):
    import json

    import app.crawler as cr
    monkeypatch.setattr(cr, "DATA_DIR", tmp_path)
    (tmp_path / "termine.json").write_text(json.dumps({"seminars": [{"id": "alt"}]}))
    monkeypatch.setattr(cr, "load_fixtures", lambda: ([{"url": "https://x/", "text": "t"}], {"seminars": []}))
    cr.run(from_fixtures=True)
    assert json.loads((tmp_path / "termine.json").read_text())["seminars"] == [{"id": "alt"}]
