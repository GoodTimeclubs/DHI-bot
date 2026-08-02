"""FastAPI-Server: Chat-API, Demo-Seite, Widget, täglicher Re-Crawl."""
from __future__ import annotations

import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import crawler, indexer, llm, retrieval
from .config import (
    ADMIN_TOKEN,
    ALLOWED_ORIGINS,
    ANTHROPIC_API_KEY_TEST,
    ANTHROPIC_MODEL,
    CONTACT,
    CRAWL_HOUR,
    CRAWL_ON_START,
    DAILY_MESSAGE_LIMIT,
    DATA_DIR,
    DETERMINISTIC_TERMINE,
    MOCK_LLM,
    TEST_TOKEN,
    TIMEZONE,
    TRUST_PROXY,
)

STATIC = Path(__file__).parent / "static"
_reindex_lock = threading.Lock()


def crawl_and_index(from_fixtures: bool = False) -> None:
    if not _reindex_lock.acquire(blocking=False):
        print("Re-Crawl läuft bereits — übersprungen.")
        return
    try:
        crawler.run(from_fixtures=from_fixtures)
        indexer.build_index()
    except Exception as e:  # noqa: BLE001
        print(f"!! Crawl/Index fehlgeschlagen: {type(e).__name__}: {e}")
        print("   Der Bot läuft mit dem letzten funktionierenden Datenstand weiter.")
    finally:
        _reindex_lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    has_index = (DATA_DIR / "index.pkl").exists()
    if CRAWL_ON_START == "always" or (CRAWL_ON_START == "auto" and not has_index):
        threading.Thread(target=crawl_and_index, daemon=True).start()
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(crawl_and_index, "cron", hour=CRAWL_HOUR, minute=10)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="DHI Bot", version="0.3.2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Absicherung: IP-Ermittlung, Rate-Limit, Tageslimit ───────────────────────

def _client_ip(request: Request) -> str:
    """Echte Besucher-IP — hinter Reverse Proxy (TRUST_PROXY=1) aus
    X-Forwarded-For; der LETZTE Eintrag stammt vom eigenen Proxy und ist
    nicht vom Client fälschbar."""
    if TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[-1].strip()
    return request.client.host if request.client else "?"


_hits: dict[str, list[float]] = {}


def _rate_ok(ip: str, limit: int = 20, window: int = 300) -> bool:
    now = time.time()
    if len(_hits) > 5000:  # Speicher begrenzen: alte IPs aufräumen
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > window]:
            _hits.pop(k, None)
    hits = [t for t in _hits.get(ip, []) if now - t < window]
    if len(hits) >= limit:
        _hits[ip] = hits
        return False
    hits.append(now)
    _hits[ip] = hits
    return True


_daily = {"date": "", "count": 0, "test_count": 0}


def _daily_roll() -> None:
    today = time.strftime("%Y-%m-%d")
    if _daily["date"] != today:
        _daily.update(date=today, count=0, test_count=0)


def _daily_ok() -> bool:
    """Globale Kostenbremse: begrenzt die Nachrichten pro Kalendertag."""
    _daily_roll()
    if DAILY_MESSAGE_LIMIT and _daily["count"] >= DAILY_MESSAGE_LIMIT:
        return False
    _daily["count"] += 1
    return True


def _qs_key(x_dhi_test: str) -> str | None:
    """Prüft den QS-Header und liefert den Test-API-Key (None = normaler Betrieb).

    Der Testkatalog stellt echte Chat-Anfragen an genau diesen Server. Ohne
    getrennten Schlüssel ginge jeder Lauf vom Produktivguthaben ab — wäre das
    leer, verstummte der Bot für echte Besucher. Ein falscher Token wird
    deshalb abgewiesen, statt still auf den Produktivpfad zurückzufallen: Eine
    kaputte QS-Konfiguration soll auffallen, nicht heimlich Guthaben ausgeben.
    """
    if not x_dhi_test:
        return None
    if not TEST_TOKEN or not secrets.compare_digest(x_dhi_test, TEST_TOKEN):
        raise HTTPException(403, "Ungültiger Test-Token.")
    if not ANTHROPIC_API_KEY_TEST:
        raise HTTPException(
            503,
            "Test-Token akzeptiert, aber kein ANTHROPIC_API_KEY_TEST konfiguriert — "
            "der Lauf würde sonst das Produktivguthaben verbrauchen.",
        )
    return ANTHROPIC_API_KEY_TEST


_LIMIT_REPLY = (
    "Vielen Dank für das große Interesse! Ich habe mein heutiges Anfrage-Limit "
    "erreicht. Das DHI-Team hilft Ihnen gern direkt weiter: "
    f"Telefon {CONTACT['telefon']}, [Beratung per WhatsApp]({CONTACT['whatsapp_link']}) "
    f"oder per E-Mail an {CONTACT['email']}."
)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    history: list[dict] = Field(default_factory=list, max_length=20)


@app.post("/api/chat")
def chat(body: ChatIn, request: Request, x_dhi_test: str = Header(default="")):
    qs_key = _qs_key(x_dhi_test)
    if qs_key is None:
        ip = _client_ip(request)
        if not _rate_ok(ip):
            raise HTTPException(429, "Zu viele Anfragen, bitte kurz warten.")
        if not _daily_ok():
            return {"reply": _LIMIT_REPLY, "sources": [], "mock": False}
    else:
        # QS-Verkehr wird getrennt gezählt: Er darf die Kostenbremse für echte
        # Besucher weder auslösen noch aufbrauchen, und das IP-Rate-Limit
        # (20 / 5 Min) würde einen Kataloglauf sonst künstlich strecken.
        _daily_roll()
        _daily["test_count"] += 1
    if not (DATA_DIR / "index.pkl").exists():
        return {
            "reply": "Ich lade gerade die Website-Inhalte, bitte in etwa einer Minute "
            "noch einmal versuchen.",
            "sources": [],
            "mock": MOCK_LLM,
        }
    try:
        return llm.answer(body.message, body.history, api_key=qs_key)
    except Exception as e:  # noqa: BLE001
        print(f"!! Chat-Fehler: {type(e).__name__}: {e}")
        raise HTTPException(502, "Antwort derzeit nicht möglich, bitte später erneut versuchen.")


@app.get("/api/health")
def health():
    _daily_roll()
    return {
        "status": "ok",
        "model": ANTHROPIC_MODEL,
        "mock_mode": MOCK_LLM,
        "deterministic_termine": DETERMINISTIC_TERMINE,
        "messages_today": _daily["count"],
        "daily_limit": DAILY_MESSAGE_LIMIT,
        # Läuft der QS-Katalog über einen eigenen Schlüssel? Der Smoke-Test der
        # Pipeline prüft das, damit ein Lauf nicht unbemerkt aufs Produktivguthaben geht.
        "test_key_configured": bool(ANTHROPIC_API_KEY_TEST and TEST_TOKEN),
        "test_messages_today": _daily["test_count"],
        **retrieval.stats(),
    }


@app.get("/api/termine")
def termine():
    """Der Terminstand, aus dem der Bot gerade antwortet (data/termine.json).

    Öffentlich, weil die Daten es auch sind: Sie stammen 1:1 aus dem
    Seminarkalender der Website und stecken ohnehin in jeder Terminantwort.

    Gebraucht wird der Endpunkt vom QS-Lauf der CI/CD-Pipeline. Der prüft, ob
    der Bot z.B. den frühesten passenden Termin nennt, und braucht dafür die
    Solldaten. Sie direkt von der Website zu holen scheitert: GitHub-Runner
    kommen dort nicht durch (Verbindungsabbruch, offenbar werden
    Rechenzentrums-IPs geblockt). Hier gelesen ist es ohnehin die
    aussagekräftigere Quelle — geprüft wird gegen genau die Daten, die der
    Bot kennt, nicht gegen einen Stand, den er noch gar nicht gecrawlt hat.
    """
    pfad = DATA_DIR / "termine.json"
    if not pfad.exists():
        raise HTTPException(503, "Termine noch nicht geladen.")
    return FileResponse(pfad, media_type="application/json")


@app.post("/api/reindex")
def reindex(x_admin_token: str = Header(default="")):
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "Ungültiger Admin-Token.")
    threading.Thread(target=crawl_and_index, daemon=True).start()
    return {"status": "Re-Crawl gestartet (läuft im Hintergrund)."}


@app.get("/")
def demo():
    return FileResponse(STATIC / "demo.html")


@app.get("/widget.js")
def widget():
    # Kurzer Browser-Cache (5 Min): Widget-Updates greifen zügig, ohne dass
    # das Institut das Einbindungs-Snippet je anfassen muss.
    return FileResponse(
        STATIC / "widget.js",
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )
