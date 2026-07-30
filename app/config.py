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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
# Niedrige Temperature = konsistente, regelkonforme Beratung (QS-Befund:
# bei Default 1.0 schwankten Länge, Links und Formatierung stark je Lauf).
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.3"))

# Mock-Modus: ohne API-Key antwortet der Bot mit gefundenen Quellen statt LLM-Text
MOCK_LLM = os.getenv("MOCK_LLM", "").lower() in ("1", "true", "yes") or not ANTHROPIC_API_KEY

CRAWL_ON_START = os.getenv("CRAWL_ON_START", "auto").lower()  # auto | always | never
CRAWL_HOUR = int(os.getenv("CRAWL_HOUR", "3"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.5"))
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
