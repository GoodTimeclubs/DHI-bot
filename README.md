# DHI Bot — Prototyp (v0.1)

Chat-Assistent für **deutsches-hypnoseinstitut.de**: beantwortet Besucherfragen zu
Website-Inhalten, Ausbildungen, tagesaktuellen Terminen und zur Buchung —
auf Basis eines täglichen Website-Crawls und der Claude API.

## Architektur

```
Besucher → widget.js (Chat) → Caddy (HTTPS) → FastAPI /api/chat → BM25-Retrieval → Claude API
                                                        ▲
     täglicher Crawl (03:10 Uhr) ───────────────────────┘
     ├─ Sitemap: Hauptdomain + hybrid. + experte.
     ├─ Termine: assets/js/dhi-seminarkalender.js (strukturiert geparst)
     └─ Buchungsseiten: dhi2.de (Ablefy) — Preise, Raten, Restplätze
```

## Schnellstart (Docker)

```bash
cp .env.example .env        # optional: ANTHROPIC_API_KEY eintragen
docker compose up --build
```

Dann im Browser: **http://localhost**

- Beim ersten Start crawlt der Bot die Website automatisch (dauert 1–3 Minuten;
  Fortschritt siehe `docker compose logs -f`).
- **Ohne API-Key** läuft der **Mock-Modus**: Der Bot zeigt zu jeder Frage die
  gefundenen Quellen und Termine — ideal, um die Daten-Pipeline kostenlos zu prüfen.
- **Mit API-Key** (`.env`) antwortet Claude frei formuliert.
- **Caddy** läuft als Reverse Proxy mit (lokal ohne TLS). Der Bot-Container hängt in einem
  internen Backend-Netz ohne veröffentlichte Ports — erreichbar ist er nur über Caddy.
  Direktzugriff fürs Debugging: `docker compose exec caddy wget -qO- http://dhi-bot:8080/api/health`

### Offline-Test ohne Internet

Mitgelieferte Beispieldaten (Stand 29.07.2026) statt Live-Crawl laden:

```bash
docker compose run --rm dhi-bot python -m app.crawler --from-fixtures
docker compose run --rm dhi-bot python -m app.indexer
docker compose up
```

## Endpunkte

| Endpunkt | Beschreibung |
|---|---|
| `GET /` | Demo-Seite mit eingebettetem Widget |
| `GET /widget.js` | Einbettbares Chat-Widget |
| `POST /api/chat` | `{"message": "...", "history": [...]}` → `{"reply", "sources", "mock"}` |
| `GET /api/health` | Status: Index-Größe, Termine, Modell, Mock-Modus |
| `POST /api/reindex` | Manueller Re-Crawl (Header `X-Admin-Token: <ADMIN_TOKEN>`) |

➜ **Ausführliche API-Dokumentation mit Beispielen (curl/PowerShell/JS): [API.md](API.md)**
   Interaktive Swagger-Übersicht im Betrieb unter `/docs`.

## Wichtige Einstellungen (`.env`)

- `ANTHROPIC_API_KEY` — ohne Key: Mock-Modus
- `ANTHROPIC_MODEL` — Standard: `claude-haiku-4-5-20251001` (günstig/schnell)
- `CRAWL_ON_START` — `auto` (Standard) | `always` | `never`
- `CRAWL_HOUR` — Stunde des täglichen Re-Crawls (Europe/Berlin)
- `ALLOWED_ORIGINS` — für den Produktivbetrieb auf die Website-Domains einschränken
- `DOMAIN` — leer = lokal (`http://localhost`); produktiv die Bot-Domain eintragen,
  Caddy holt dann automatisch TLS-Zertifikate (Let's Encrypt)

## Einbindung auf der echten Website (später)

1. Bot auf einem VPS deployen: DNS der Bot-Subdomain auf den Server zeigen lassen und
   `DOMAIN=bot.…` in der `.env` setzen — der mitlaufende Caddy übernimmt HTTPS automatisch.
2. `ALLOWED_ORIGINS=https://deutsches-hypnoseinstitut.de,...` setzen.
3. Der Website-Betreiber ergänzt vor `</body>`:
   `<script src="https://BOT-DOMAIN/widget.js" data-api="https://BOT-DOMAIN" defer></script>`
4. Datenschutzerklärung ergänzen (siehe Umsetzungsplan im Projekt).

## Sicherheit

- **Eingaben begrenzt & validiert** (Nachricht ≤ 1500 Zeichen, Verlauf gekappt); Fehlermeldungen ohne Interna.
- **Rate-Limit**: 20 Nachrichten / 5 Min / IP. `TRUST_PROXY=1` (Standard in `.env`) liest
  die echte Besucher-IP aus dem von Caddy gesetzten `X-Forwarded-For`.
- **Kostenbremse**: `DAILY_MESSAGE_LIMIT` (Standard 1000/Tag, 0 = aus) — danach verweist der
  Bot freundlich auf Telefon/WhatsApp/E-Mail. Zusätzlich empfohlen: Spend-Limit in der
  Anthropic-Console setzen.
- **Netztrennung**: Der Bot läuft in einem internen Docker-Backend-Netz und veröffentlicht
  keine Ports — von außen ist nur Caddy (Ports 80/443) erreichbar.
- **Container läuft als non-root** (User `botuser`, UID 10001). Auf einem Linux-Host braucht
  das Daten-Volume einmalig Schreibrecht: `sudo chown -R 10001 data/` (unter Docker Desktop
  für Windows/Mac nicht nötig).
- **XSS-Schutz im Widget** (HTML-Escaping + Shadow DOM), API-Key nur serverseitig in `.env`,
  Chats werden serverseitig nicht gespeichert.
- **Produktiv-Checkliste**: `DOMAIN` in `.env` setzen (HTTPS übernimmt der mitlaufende Caddy),
  `ALLOWED_ORIGINS` auf die DHI-Domains setzen, `ADMIN_TOKEN` ändern, AVV mit Anthropic
  abschließen, Datenschutzerklärung der Website ergänzen.

## Bewusste Grenzen des Prototyps

- BM25-Volltextsuche statt Embeddings (bei ~40 Seiten völlig ausreichend; Embeddings
  lassen sich später in `indexer.py`/`retrieval.py` ergänzen).
- Chats werden **nicht gespeichert** (nur flüchtig im Browser-Tab) — datenschutzfreundlich.
- Rate-Limit in-memory (20 Nachrichten / 5 Min / IP).
