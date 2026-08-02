"""Zentrale Konfiguration — alles per Umgebungsvariable steuerbar (.env)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIXTURES_DIR = ROOT / "fixtures"

# ── Crawl-Umfang ─────────────────────────────────────────────────────────────
MAIN_DOMAIN = "deutsches-hypnoseinstitut.de"

# Hauptdomain + alle Subdomains, die der tägliche Crawl erfassen soll
# (Reihenfolge = Crawl-Priorität, Hauptdomain zuerst). legal.… ist bewusst
# enthalten: dort erscheinen später die neuen AGB — bis dahin zeigt die
# Subdomain nur eine Hoster-Platzhalterseite, die der Crawler erkennt und
# überspringt (siehe crawler.is_placeholder_page).
_DEFAULT_CRAWL_DOMAINS = ",".join(
    [MAIN_DOMAIN]
    + [
        f"{sub}.{MAIN_DOMAIN}"
        for sub in (
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
        )
    ]
)


def parse_domain_list(raw: str) -> list[str]:
    """Kommagetrennte Domain-Liste → saubere Hostnamen (ohne Schema/Pfad/www.)."""
    hosts: list[str] = []
    for part in raw.split(","):
        h = part.strip().lower().removeprefix("https://").removeprefix("http://")
        h = h.split("/", 1)[0].removeprefix("www.")
        if h and h not in hosts:
            hosts.append(h)
    return hosts


CRAWL_DOMAINS = parse_domain_list(os.getenv("CRAWL_DOMAINS", _DEFAULT_CRAWL_DOMAINS))

# ── Standorte & standortabhängige Preise ─────────────────────────────────────
# Orte mit festen, im Seminarkalender veröffentlichten Terminen (zusätzlich zur
# Live-Online-Theorie der DHI 2.0). Die Vollpräsenz DHI 1.0 findet ausschließlich
# in Aschaffenburg statt; Leipzig und Stuttgart sind Übungsstandorte.
AUSBILDUNGSSTANDORTE = ["Aschaffenburg", "Leipzig", "Stuttgart"]

# Weitere Übungsstandorte der DHI 2.0 laut Website (hybrid.…/uebungstage-standorte):
# verfügbar, aber ohne feste Termine — die Terminplanung startet mit der ersten
# verbindlichen Anmeldung. Diese Orte dürfen NICHT verneint werden.
UEBUNGSSTANDORTE_AUF_ANFRAGE = ["Hamburg", "Oberstaufen-Steibis", "Gallicano (Toskana)"]

# Orte, die auf den DHI-Seiten vorkommen, aber KEIN Ausbildungs- oder
# Übungsstandort sind — mit der jeweiligen Erklärung. Berlin ist der Fall aus
# dem Live-Betrieb: dort gibt es eine DHI-Hypnosepraxis (Einzelsitzungen), aber
# keine Ausbildung, und ältere Kundenstimmen nennen Berlin als früheren
# Seminarort, was das Modell sonst als aktuelles Angebot missversteht.
KEINE_AUSBILDUNGSSTANDORTE = {
    "Berlin": (
        "weder Ausbildungs- noch Übungsstandort. In Berlin gibt es ausschließlich "
        "eine DHI-Hypnosepraxis (Einzelsitzungen/Coaching, Taina Ebert-Rall) — die "
        "bleibt selbstverständlich buchbar. Ältere Kundenstimmen erwähnen Berlin als "
        "früheren Seminarort; eine Ausbildung ist dort heute nicht buchbar."
    ),
}

# Standortabhängige Preise der Präsenz-Übungstage (DHI 2.0).
#
# Hintergrund: Die Ablefy-Produktseite nennt nur EINEN Basispreis (den von
# Aschaffenburg). Die tatsächlichen Preise je Standort stehen erst auf der
# Checkout-Seite (Produkt-URL + "/payment"), weil die Übungstage dort als
# einzelne Standort-Tickets angeboten werden ("Die Preise sind abhängig vom
# Aufwand und den Extra-Kosten an externen Standorten"). Ohne diese Trennung
# nannte der Bot für Leipzig und Stuttgart fälschlich den Aschaffenburger Preis.
#
# Der tägliche Crawl liest die Standortpreise selbst aus (crawler.
# fetch_preisvarianten) und legt sie in termine.json unter "preisvarianten" ab.
# Diese Tabelle ist der FALLBACK, falls der Checkout-Abruf scheitert oder die
# Seite umgebaut wird — bei einer Preisänderung hier nachziehen.
# Stand: 01.08.2026 (Checkout-Seiten practice12/practice3 geprüft).
UEBUNGSTAGE_PREISE_FALLBACK = {
    "practice12": {
        "Aschaffenburg": "1.196,00 €",
        "Leipzig": "1.496,00 €",
        "Stuttgart": "1.496,00 €",
    },
    "practice3": {
        "Aschaffenburg": "1.196,00 €",
        "Leipzig": "1.496,00 €",
        "Stuttgart": "1.496,00 €",
    },
}

# Feste Klarstellungen, die NICHT auf der Website stehen, zu denen der Bot aber
# eine verbindliche Antwort geben muss (sonst rät das Modell oder sagt nur
# „weiß ich nicht"). Werden wörtlich in den System-Prompt übernommen.
# Erweiterbar: pro Eintrag ein Auslöser und die verbindliche Aussage.
KLARSTELLUNGEN = [
    {
        "thema": "Katrin Winkelmann",
        "aussage": (
            "Frau Katrin Winkelmann war bis 2025 für das Deutsche Hypnoseinstitut (DHI) "
            "tätig. Aktuell besteht jedoch keine Zusammenarbeit mehr. "
            "Frau Winkelmann ist derzeit nicht berechtigt, Ausbildungen im Namen des DHI "
            "durchzuführen oder DHI-Zertifikate auszustellen."
        ),
    },
]

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
# Niedrige Temperature = konsistente, regelkonforme Beratung (QS-Befund:
# bei Default 1.0 schwankten Länge, Links und Formatierung stark je Lauf).
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.3"))

# Mock-Modus: ohne API-Key antwortet der Bot mit gefundenen Quellen statt LLM-Text
MOCK_LLM = os.getenv("MOCK_LLM", "").lower() in ("1", "true", "yes") or not ANTHROPIC_API_KEY

# Reine Terminlistenfragen deterministisch aus termine.json beantworten statt
# per LLM-Auswahl (QS-Befund 8: Modell ließ selten den frühesten Termin aus).
# 0 = abschalten, dann beantwortet wieder das LLM alle Terminfragen.
DETERMINISTIC_TERMINE = os.getenv("DETERMINISTIC_TERMINE", "1").lower() in ("1", "true", "yes")

CRAWL_ON_START = os.getenv("CRAWL_ON_START", "auto").lower()  # auto | always | never
CRAWL_HOUR = int(os.getenv("CRAWL_HOUR", "3"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.5"))

# Obergrenze der Website-Seiten pro Crawl-Lauf — Schutz, falls eine Subdomain
# stark wächst. Stand 01.08.2026 hat der volle Crawl ~570 Seiten (praxen und
# hypnospathie sind groß); 600 lässt etwas Luft — erscheint im Log die Meldung
# „Seitenlimit erreicht", hier bzw. per .env erhöhen.
MAX_PAGES = int(os.getenv("MAX_PAGES", "600"))
TIMEZONE = os.getenv("TZ", "Europe/Berlin")

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# Hinter einem Reverse Proxy (nginx/Caddy) auf 1 setzen: dann wird die echte
# Besucher-IP aus X-Forwarded-For gelesen (letzter Eintrag = vom Proxy gesetzt).
TRUST_PROXY = os.getenv("TRUST_PROXY", "").lower() in ("1", "true", "yes")

# Globale Kostenbremse: maximale Chat-Nachrichten pro Tag über alle Besucher.
# 0 = deaktiviert. Zähler liegt im RAM (Neustart setzt ihn zurück).
DAILY_MESSAGE_LIMIT = int(os.getenv("DAILY_MESSAGE_LIMIT", "1000"))

# Kontaktdaten des Instituts (für Eskalation in Antworten).
# whatsapp_link ist der EINZIGE WhatsApp-Link, den der Bot verwenden darf —
# das Modell darf Nummern nie selbst in Links umrechnen (QS-Befund: Tippfehler).
CONTACT = {
    "telefon": "06021 920 8003",
    "whatsapp": "0151 544 344 70",
    "whatsapp_link": "https://wa.me/4915154434470",
    "email": "info@deutsches-hypnoseinstitut.de",
    "kontakt_url": "https://deutsches-hypnoseinstitut.de/kontakt.html",
}
