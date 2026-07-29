# DHI Bot — API-Dokumentation (v0.2)

REST-API des DHI-Chatbots. Alle Anfragen und Antworten sind JSON (UTF-8).

**Basis-URL:** lokal `http://localhost:8080`, produktiv `https://<bot-domain>`.

Eine interaktive Übersicht (Swagger UI) liefert FastAPI automatisch unter
**`/docs`**, das maschinenlesbare Schema unter `/openapi.json`.

---

## Übersicht

| Methode | Pfad | Zweck | Auth |
|---|---|---|---|
| `POST` | `/api/chat` | Chat-Nachricht beantworten | keine (öffentlich) |
| `GET` | `/api/health` | Status, Datenstand, Zähler | keine |
| `POST` | `/api/reindex` | Website neu crawlen + Index neu bauen | `X-Admin-Token` |
| `GET` | `/` | Demo-Seite mit eingebettetem Widget | keine |
| `GET` | `/widget.js` | Einbettbares Chat-Widget (JavaScript) | keine |

---

## POST /api/chat

Beantwortet eine Besucherfrage auf Basis der gecrawlten Website-Inhalte und
der tagesaktuellen Termindaten.

### Request

```json
{
  "message": "Wann ist der nächste Kurs Stufe 1+2?",
  "history": [
    { "role": "user",      "content": "Was ist DHI 2.0?" },
    { "role": "assistant", "content": "DHI 2.0 verbindet Live-Online-Unterricht…" }
  ]
}
```

| Feld | Typ | Pflicht | Regeln |
|---|---|---|---|
| `message` | string | ja | 1–1500 Zeichen |
| `history` | array | nein | max. 20 Einträge; nur die letzten 10 werden verwendet; `content` wird pro Eintrag auf 2000 Zeichen gekürzt; andere `role`-Werte als `user`/`assistant` werden ignoriert |

Der Server ist **zustandslos**: Es gibt keine Session — der Client schickt den
bisherigen Gesprächsverlauf selbst mit (so macht es auch das mitgelieferte Widget).
Serverseitig wird nichts gespeichert.

### Response `200 OK`

```json
{
  "reply": "Die nächste Vollpräsenz-Ausbildung Stufe 1+2 startet am 21.09.2026 in Aschaffenburg: [Jetzt Termin sichern](https://dhi2.de/…) Welcher Weg passt besser zu Ihnen?",
  "sources": [
    { "url": "https://deutsches-hypnoseinstitut.de/seminarkalender.html", "title": "Seminarkalender" }
  ],
  "mock": false
}
```

| Feld | Typ | Bedeutung |
|---|---|---|
| `reply` | string | Antworttext. Links können im Format `[Beschriftung](URL)` enthalten sein — das Widget rendert sie als Buttons. |
| `sources` | array | Bis zu 4 Quellseiten (`url`, `title`), aus denen die Antwort gespeist wurde. |
| `mock` | bool | `true` = Testmodus ohne `ANTHROPIC_API_KEY` (zeigt Fundstellen statt LLM-Antwort). |

**Sonderfälle mit Status 200** (bewusst kein Fehler, damit das Widget sie normal anzeigt):

- Index wird gerade erstmalig aufgebaut → `reply` bittet, es in ca. einer Minute erneut zu versuchen.
- Tageslimit erreicht (`DAILY_MESSAGE_LIMIT`) → `reply` verweist freundlich auf Telefon/WhatsApp/E-Mail.

### Fehler

| Status | Bedeutung | Body |
|---|---|---|
| `422` | Validierung fehlgeschlagen (z.B. `message` fehlt oder > 1500 Zeichen) | FastAPI-Standardformat `{"detail": [...]}` |
| `429` | Rate-Limit: mehr als **20 Nachrichten in 5 Minuten pro IP** | `{"detail": "Zu viele Anfragen — bitte kurz warten."}` |
| `502` | LLM-Aufruf fehlgeschlagen (z.B. API nicht erreichbar) | `{"detail": "Antwort derzeit nicht möglich — bitte später erneut versuchen."}` |

### Beispiele

**curl (Bash):**

```bash
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Was kostet die Ausbildung Stufe 1+2?", "history": []}'
```

**PowerShell (Windows):**

```powershell
Invoke-RestMethod -Uri "http://localhost:8080/api/chat" -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body (@{ message = "Wann ist der nächste Termin in Leipzig?"; history = @() } | ConvertTo-Json)
```

**JavaScript (fetch, wie im Widget):**

```js
const res = await fetch("https://bot.example.de/api/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "Wie läuft DHI 2.0 ab?", history }),
});
const { reply, sources, mock } = await res.json();
```

---

## GET /api/health

Status- und Monitoring-Endpunkt (z.B. für UptimeRobot).

```json
{
  "status": "ok",
  "model": "claude-haiku-4-5-20251001",
  "mock_mode": false,
  "messages_today": 42,
  "daily_limit": 1000,
  "index_built_at": "2026-07-29T13:04:32+00:00",
  "chunks": 187,
  "termine": 30,
  "termine_fetched_at": "2026-07-29T03:10:04+00:00"
}
```

| Feld | Bedeutung |
|---|---|
| `mock_mode` | `true`, wenn kein API-Key gesetzt ist |
| `messages_today` | heute gezählte Chat-Nachrichten (RAM-Zähler, Neustart setzt zurück) |
| `daily_limit` | konfiguriertes Tageslimit (`0` = deaktiviert) |
| `index_built_at` / `chunks` | Stand und Größe des Suchindex |
| `termine` / `termine_fetched_at` | Anzahl und Stand der Termindaten aus dem Seminarkalender |

---

## POST /api/reindex

Stößt Crawl + Indexaufbau im Hintergrund an (läuft sonst automatisch täglich
um `CRAWL_HOUR`:10 Uhr). Geschützt über den Header `X-Admin-Token`, dessen Wert
`ADMIN_TOKEN` aus der `.env` entsprechen muss. Ist `ADMIN_TOKEN` leer, ist der
Endpunkt komplett deaktiviert (immer `403`).

```bash
curl -X POST https://bot.example.de/api/reindex -H "X-Admin-Token: MEIN-TOKEN"
```

Antwort `200`: `{"status": "Re-Crawl gestartet (läuft im Hintergrund)."}` —
läuft bereits ein Crawl, wird der neue Aufruf übersprungen (siehe Server-Log).
Falscher/fehlender Token: `403`.

---

## Widget-Einbindung (fertiger API-Client)

Das mitgelieferte Widget übernimmt Verlauf, Rendering (Buttons, Listen) und
Fehlerbehandlung. Einbindung auf einer Website mit einer Zeile vor `</body>`:

```html
<script src="https://bot.example.de/widget.js" data-api="https://bot.example.de" defer></script>
```

`data-api` ist optional — ohne das Attribut nutzt das Widget den Origin, von dem
`widget.js` geladen wurde.

---

## Relevante Konfiguration (`.env`)

| Variable | Wirkung auf die API |
|---|---|
| `ANTHROPIC_API_KEY` | leer → alle `/api/chat`-Antworten im Mock-Modus (`mock: true`) |
| `ANTHROPIC_MODEL`, `MAX_TOKENS` | verwendetes Modell / max. Antwortlänge |
| `ALLOWED_ORIGINS` | CORS: welche Websites `/api/chat` aus dem Browser aufrufen dürfen (produktiv auf die DHI-Domains einschränken) |
| `TRUST_PROXY` | `1` hinter Reverse Proxy: echte Besucher-IP aus `X-Forwarded-For` fürs Rate-Limit |
| `DAILY_MESSAGE_LIMIT` | globale Kostenbremse pro Kalendertag (`0` = aus) |
| `ADMIN_TOKEN` | Token für `/api/reindex` |
| `CRAWL_ON_START`, `CRAWL_HOUR` | automatischer Crawl beim Start / täglicher Re-Crawl |
