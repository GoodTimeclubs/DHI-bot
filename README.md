# DHI Bot (v0.3.2)

Chat-Assistent für **deutsches-hypnoseinstitut.de** und alle DHI-Subdomains:
beantwortet Besucherfragen zu Website-Inhalten, Ausbildungen, dem
Praxen-Netzwerk, tagesaktuellen Terminen und zur Buchung — auf Basis eines
täglichen Website-Crawls und der Claude API.

## Architektur

```
Besucher → widget.js (Chat) → Caddy (HTTPS) → FastAPI /api/chat → BM25-Retrieval → Claude API
                                                        ▲    └→ reine Terminlistenfragen:
     täglicher Crawl (03:10 Uhr) ───────────────────────┘       deterministisch aus termine.json
     ├─ Sitemap: Hauptdomain + 10 Subdomains (Liste s.u.)       (app/termine.py, ohne LLM)
     ├─ Termine: assets/js/dhi-seminarkalender.js (strukturiert geparst)
     ├─ Buchungsseiten: dhi2.de (Ablefy) — Preise, Raten, Restplätze
     └─ Checkout-Seiten (…/payment) — standortabhängige Preise der Übungstage
```

**Standortabhängige Preise (v0.3.2):** Die Ablefy-Produktseite der Präsenz-Übungstage
nennt nur *einen* Basispreis (den von Aschaffenburg). Tatsächlich kosten die Übungstage
je nach Ort unterschiedlich viel („Die Preise sind abhängig vom Aufwand und den
Extra-Kosten an externen Standorten"); die einzelnen Standort-Tickets stehen erst im
Checkout (Produkt-URL + `/payment`). Der tägliche Crawl liest sie dort aus und legt sie
in `data/termine.json` unter `preisvarianten` ab; der System-Prompt bekommt daraus einen
`STANDORTPREISE`-Block und darf einen Ortspreis nie auf einen anderen Ort übertragen.
Scheitert der Checkout-Abruf oder deckt er nicht alle Standorte des Produkts ab, greift
die gepflegte Tabelle `UEBUNGSTAGE_PREISE_FALLBACK` in `app/config.py` — **dort bei einer
Preisänderung nachziehen**. Weicht der Crawl von dieser Tabelle ab, steht ein Hinweis im
Crawl-Log.

**Deterministische Terminantworten (v0.2.3, QS-Befund 8):** Eindeutige
Terminlistenfragen („Welche Übungstage gibt es in Stuttgart?") beantwortet der Bot
per strukturiertem Filter über `data/termine.json` — chronologisch, der früheste
passende Termin kann nie mehr ausgelassen werden, Antwortzeit < 0,5 s, keine
API-Kosten. Das Gating ist bewusst konservativ: Preise, Buchung, unbekannte
Wunsch-Orte („… in Frankfurt?"), Konzept- und Folgefragen laufen weiter über das
LLM, das Alternativen und Beratung anbieten kann. Abschaltbar per
`DETERMINISTIC_TERMINE=0`.

## Erfasste Domains

Der tägliche Crawl liest die Hauptdomain und alle DHI-Subdomains ein
(änderbar per `CRAWL_DOMAINS` in der `.env`):

| Domain | Inhalt |
|---|---|
| deutsches-hypnoseinstitut.de | Institut, Ausbildungen, Hypnosewissen, FAQ, Seminarkalender |
| lars.… | Lars Gutzeit — Vita, Hypnose, Coaching, Autor & Medien |
| nautilus-code.… | Der Nautilus-Code (vierstufiges Hypnoseprotokoll) |
| hypnospathie.… | Hypnospathie — Ethik, Wissensdatenbank, Hypnotiseurverzeichnis |
| hypnosepraxis-aschaffenburg.… | DHI Hypnosepraxis Aschaffenburg |
| hypnosepraxis-berlin.… | DHI Hypnosepraxis Berlin |
| hypnosepraxis-oberstaufen.… | DHI Hypnosepraxis Oberstaufen-Steibis |
| praxen.… | Überblick über das DHI-Praxen-Netzwerk |
| hybrid.… | DHI 2.0 Live-Hybrid |
| experte.… | Experten |
| legal.… | Rechtliches — hier erscheinen später die neuen AGB |

Dazu kommen wie bisher der Seminarkalender (`dhi-seminarkalender.js`) und die
sechs Ablefy-Buchungsseiten auf dhi2.de.

Noch unbefüllte Subdomains sind unkritisch: Hoster-Platzhalterseiten (z.B. die
Hostinger-Default-Seite, die legal.… bis zum Einstellen der AGB zeigt) erkennt
der Crawler und hält sie aus dem Index — sobald dort echte Inhalte liegen,
nimmt der nächste tägliche Crawl sie automatisch auf. Fällt eine Subdomain
aus, läuft der Crawl mit den übrigen Domains weiter. Inhaltsgleiche Duplikate
(`…/index.html`-Zwillinge, URL-Query-Varianten wie `praxen.…/?bereich=…`,
Soft-404-Seiten) werden beim Crawl automatisch übersprungen, damit sie die
Suchtreffer nicht verwässern.

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
| `GET /widget.js` | Einbettbares Chat-Widget (`Cache-Control: public, max-age=300`) |
| `POST /api/chat` | `{"message": "...", "history": [...]}` → `{"reply", "sources", "mock"}` |
| `GET /api/health` | Status: Index-Größe, Termine, Modell, Mock-Modus |
| `GET /api/termine` | Terminstand, aus dem der Bot antwortet (Solldaten für den QS-Lauf) |
| `POST /api/reindex` | Manueller Re-Crawl (Header `X-Admin-Token: <ADMIN_TOKEN>`) |

➜ **Ausführliche API-Dokumentation mit Beispielen (curl/PowerShell/JS): [API.md](API.md)**
   Interaktive Swagger-Übersicht im Betrieb unter `/docs`.

## Inhaltliche Regeln pflegen (ohne .env)

Ein Teil des Bot-Verhaltens ist bewusst nicht per Umgebungsvariable, sondern in
`app/config.py` hinterlegt — dort steht alles an einer Stelle und wird von den
Unit-Tests abgesichert:

| Konstante | Wofür |
|---|---|
| `AUSBILDUNGSSTANDORTE` | Orte mit festen Terminen im Kalender (Aschaffenburg, Leipzig, Stuttgart) |
| `UEBUNGSSTANDORTE_AUF_ANFRAGE` | Verfügbare Übungsstandorte ohne feste Termine (Hamburg, Oberstaufen-Steibis, Gallicano) — dürfen nie verneint werden |
| `KEINE_AUSBILDUNGSSTANDORTE` | Orte, die *keine* Ausbildungs- oder Übungsstandorte sind, mit Erklärung — aktuell nur **Berlin** (dort nur die DHI-Hypnosepraxis). Ohne diesen Hinweis las das Modell aus alten Kundenstimmen einen Standort heraus. |
| `UEBUNGSTAGE_PREISE_FALLBACK` | Standortpreise der Übungstage als Rückfallebene zum Checkout-Crawl |
| `KLARSTELLUNGEN` | Verbindliche Aussagen, die nicht auf der Website stehen (z.B. zur Zusammenarbeit mit einzelnen Personen). Wörtlich übernommen, erweiterbar um weitere Einträge `{thema, aussage}`. |

Verhaltensregeln, die dazugehören, stehen im System-Prompt (`app/llm.py`):
Standortpreise nie auf einen anderen Ort übertragen (Regel 6), Terminantworten
enden mit dem Button zur Terminseite (Regel 5), Nicht-Standorte klar verneinen
und Alternative anbieten (Regel 11), bei unklarem Anliegen erst eine Rückfrage
„Ausbildung oder Hypnose für sich selbst?" (Regel 12) und bei Skepsis aktiv das
unverbindliche Beratungsgespräch anbieten (Regel 13).

Zur Rückfrage-Regel gehört ein Gegenstück im deterministischen Terminpfad:
`app/termine.py` schickt Fragen mit Sitzungs- oder Klientenbezug („Ich möchte
eine Hypnose, wann haben Sie in Aschaffenburg einen Termin?") bewusst ans LLM,
damit dort nachgefragt statt geraten wird.

## Wichtige Einstellungen (`.env`)

- `ANTHROPIC_API_KEY` — ohne Key: Mock-Modus
- `ANTHROPIC_MODEL` — Standard: `claude-haiku-4-5-20251001` (günstig/schnell)
- `CRAWL_ON_START` — `auto` (Standard) | `always` | `never`
- `CRAWL_HOUR` — Stunde des täglichen Re-Crawls (Europe/Berlin)
- `CRAWL_DOMAINS` — erfasste Domains, kommagetrennt (Standard: alle 11
  DHI-Domains, siehe „Erfasste Domains")
- `MAX_PAGES` — Obergrenze Seiten pro Crawl-Lauf (Standard 600; der volle
  Crawl hat Stand 01.08.2026 ~570 Seiten)
- `DETERMINISTIC_TERMINE` — `1` (Standard): reine Terminlistenfragen deterministisch
  aus `termine.json` beantworten statt per LLM-Auswahl (QS-Befund 8); `0` = aus
- `ALLOWED_ORIGINS` — für den Produktivbetrieb auf die Website-Domains einschränken
- `DOMAIN` — leer = lokal (`http://localhost`); produktiv die Bot-Domain eintragen,
  Caddy holt dann automatisch TLS-Zertifikate (Let's Encrypt)

## Einbindung auf der echten Website (später)

1. Bot auf einem VPS deployen: DNS der Bot-Subdomain auf den Server zeigen lassen und
   `DOMAIN=bot.…` in der `.env` setzen — der mitlaufende Caddy übernimmt HTTPS automatisch.
2. `ALLOWED_ORIGINS` auf alle Domains setzen, auf denen das Widget eingebunden
   wird (Hauptdomain + Subdomains).
3. Der Website-Betreiber ergänzt vor `</body>`:

   ```html
   <script src="https://bot.deutsches-hypnoseinstitut.de/widget.js"
           data-api="https://bot.deutsches-hypnoseinstitut.de"
           data-desktop-bottom="96"
           data-mobile-button="off"
           defer></script>
   ```

   | Attribut | Default | Wirkung |
   |---|---|---|
   | `data-api` | Origin von `widget.js` | Basis-URL der Bot-API |
   | `data-desktop-bottom` | `20` | Abstand des Chat-Buttons vom unteren Rand in px (Ganzzahl 0–400; ungültige Werte fallen auf den Default zurück). Chat-Panel und maximale Panel-Höhe wandern mit. |
   | `data-mobile-button` | `auto` | `off` blendet den schwebenden Button bei ≤ 640 px Viewport-Breite aus — den Chat öffnen dann Elemente mit `data-dhi-chat` (CTA-Leiste) oder `window.DHIBot`. |

   Alle Attribute sind optional — ohne sie verhält sich das Widget wie bisher.

   **Rechenregel Desktop-Offset:** `data-desktop-bottom` = bottom-Wert des
   WhatsApp-Buttons + dessen Höhe + 16 px Abstand. Institut: 20 + 60 + 16 = **96**.

   **Mobile CTA-Leiste:** Das Institut baut das Chat-Element selbst in seine
   Leiste ein und markiert es mit `data-dhi-chat`, z. B.
   `<a href="#chat" data-dhi-chat>Chat</a>`. Der delegierte Listener des Widgets
   fängt Klicks auch auf nachträglich gerendertem Markup ab, unterdrückt bei
   `<a>` die Navigation und pflegt `aria-expanded`/`aria-controls` am Trigger.
   Dazu gibt es die JS-API `window.DHIBot.open()` / `.close()` / `.toggle()`
   (+ `.version`). Sicherheitsnetz: Ist `data-mobile-button="off"` gesetzt,
   aber kurz nach DOMContentLoaded kein `[data-dhi-chat]` im DOM (z. B.
   Subdomain ohne CTA-Leiste), erscheint der mobile Button trotzdem — der Chat
   bleibt überall erreichbar.
4. Datenschutzerklärung ergänzen (siehe Umsetzungsplan im Projekt).

Widget-Updates greifen ohne erneute HTML-Änderung: `/widget.js` wird mit
`Cache-Control: public, max-age=300` ausgeliefert (max. 5 Minuten Browser-Cache).

## Qualitätssicherung & Tests

Drei Test-Ebenen liegen unter `tests/` (Einrichtung: `pip install -r requirements-dev.txt`):

0. **Unit-Tests** — `pytest tests/test_termine.py tests/test_crawler.py
   tests/test_llm.py tests/test_retrieval.py` prüft
   ohne Server, ohne API-Key und ohne Internet: deterministische
   Terminantworten lassen nie den frühesten passenden Termin aus (Beratungs-,
   Preis- und Frankfurt-Fragen gehen weiter ans LLM); alle 11 DHI-Domains
   stehen im Standard-Crawl, die Platzhalter-Erkennung greift (und lässt
   künftige echte legal-Inhalte durch), Sitemap-Parsing inkl. Sitemap-Index
   und gzip funktioniert; der System-Prompt enthält die Kernregeln
   (Link-Pflichten, Preis-Trennung, Praxen-Baustein), der PREISDATEN-Block
   erfasst auch neue Ablefy-Produkte, und das Retrieval boostet
   Buchungsseiten bei Ausbildungs- (nicht aber bei Sitzungs-)Preisfragen.
   Seit v0.3.2 zusätzlich: der Checkout-Parser ordnet jedem Standort seinen
   eigenen Preis zu (layoutunabhängig, mit Fallback auf die Tabelle in
   `config.py`), jede deterministische Terminantwort endet mit dem Button zur
   Terminseite, und die verbindlichen Klarstellungen stehen wörtlich im Prompt.

1. **Testkatalog** — 59 Beispielfragen mit Soll-Verhalten (Inhalte, Termine, Preise,
   Buchung, Grenzfälle wie Gesundheitsfragen, Heilversprechen, Off-Topic,
   Prompt-Injection; Block H = Rückmeldungen aus dem Live-Betrieb) in
   `tests/testkatalog.yaml`. Der Runner prüft jede Antwort
   automatisch (Sie-Form, Formatierung, Links, WhatsApp-Nummer, Termine gegen
   `data/termine.json`, Preis-Regeln) und schreibt einen Bericht nach `tests/report/`:

   ```bash
   # Server mit echtem API-Key starten (TRUST_PROXY=1 erlaubt dem Runner,
   # das Rate-Limit per X-Forwarded-For-Rotation zu umgehen), dann:
   python tests/run_testkatalog.py --base-url http://127.0.0.1:8000
   ```

   Der Runner funktioniert gegen jede Instanz (`--base-url https://bot.…`) und ist
   damit auch der End-to-End-Test für den Produktivserver.

2. **Playwright-Widget-Checks** — 23 UI-Tests (Desktop + Mobil) in
   `tests/test_widget.py`: Vollbild-Chat auf kleinen Screens, Schließen-Button,
   Tastatur-Follow per VisualViewport, 16-px-Eingabe gegen iOS-Auto-Zoom, kein
   Auto-Fokus auf Touch-Geräten, Tippflächen, Link-Button-Renderer; seit v0.3.1
   zusätzlich die Button-Landschaft der Instituts-Website (Nachbau als
   Fixture-Seite mit WhatsApp-Float und 5-spaltiger CTA-Leiste):
   `data-desktop-bottom`-Stapelung ohne Überlagerung, Panel vollständig im
   700-px-Viewport, `data-mobile-button="off"` inkl. Sicherheitsnetz ohne
   CTA-Leiste, Öffnen per `[data-dhi-chat]` und `window.DHIBot`. Startet den
   Bot selbst im Mock-Modus (Port 8123, keine API-Kosten):

   ```bash
   playwright install chromium   # einmalig
   pytest tests/test_widget.py -v
   ```

Ergebnisse und behobene Befunde des QS-Laufs vom 30.07.2026: siehe
[docs/qs/2026-07-30-qs-bericht.md](docs/qs/2026-07-30-qs-bericht.md).

## Sicherheit

- **Eingaben begrenzt & validiert** (Nachricht ≤ 1500 Zeichen, Verlauf gekappt); Fehlermeldungen ohne Interna.
- **Rate-Limit**: 20 Nachrichten / 5 Min / IP. `TRUST_PROXY=1` (Standard in `.env`) liest
  die echte Besucher-IP aus dem von Caddy gesetzten `X-Forwarded-For`.
- **Kostenbremse**: `DAILY_MESSAGE_LIMIT` (Standard 1000/Tag, 0 = aus) — danach verweist der
  Bot freundlich auf Telefon/WhatsApp/E-Mail. Zusätzlich empfohlen: Spend-Limit in der
  Anthropic-Console setzen.
- **Netztrennung**: Der Bot läuft in einem internen Docker-Backend-Netz und veröffentlicht
  keine Ports — von außen ist nur Caddy (Ports 80/443) erreichbar.
- **Container läuft als non-root** (User `botuser`, UID 10001). Die Crawl-Daten liegen
  deshalb in einem benannten Docker-Volume (`bot_data`) statt in einem Bind-Mount:
  Windows-Bind-Mounts erscheinen im Container ohne Schreibrecht für botuser — der
  Crawl scheiterte dort mit PermissionError. Inhalt ansehen:
  `docker compose exec dhi-bot cat /app/data/meta.json`
- **XSS-Schutz im Widget** (HTML-Escaping + Shadow DOM), API-Key nur serverseitig in `.env`,
  Chats werden serverseitig nicht gespeichert.
- **Produktiv-Checkliste**: `DOMAIN` in `.env` setzen (HTTPS übernimmt der mitlaufende Caddy),
  `ALLOWED_ORIGINS` auf die DHI-Domains setzen, `ADMIN_TOKEN` ändern, AVV mit Anthropic
  abschließen, Datenschutzerklärung der Website ergänzen.

## Bewusste Grenzen des Prototyps

- BM25-Volltextsuche statt Embeddings (auch bei einigen hundert Seiten gut
  brauchbar; Embeddings
  lassen sich später in `indexer.py`/`retrieval.py` ergänzen).
- Chats werden **nicht gespeichert** (nur flüchtig im Browser-Tab) — datenschutzfreundlich.
- Rate-Limit in-memory (20 Nachrichten / 5 Min / IP).
