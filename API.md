# DHI Bot — API-Dokumentation (v0.3.2)

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
| `GET` | `/api/termine` | Terminstand, aus dem der Bot antwortet | keine |
| `POST` | `/api/reindex` | Website neu crawlen + Index neu bauen | `X-Admin-Token` |
| `GET` | `/` | Demo-Seite mit eingebettetem Widget | keine |
| `GET` | `/widget.js` | Einbettbares Chat-Widget (JavaScript); `Cache-Control: public, max-age=300` | keine |

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

## GET /api/termine

Liefert `data/termine.json` unverändert aus — also genau die Termine, aus denen
der Bot gerade antwortet. Inhalt: die aus `assets/js/dhi-seminarkalender.js`
geparsten Seminare, die `PRODUCT`-Map mit den Ablefy-Buchungslinks, die
Quell-URL und der Zeitpunkt des letzten Crawls.

```json
{
  "seminars": [
    {
      "id": "…", "kind": "presence", "stage": "1+2",
      "title": "DHI 1.0 Hypnose-Grundausbildung",
      "start": "2026-09-18", "end": "2026-09-20",
      "time": "10:00–18:00", "location": "Aschaffenburg",
      "url": "https://dhi2.de/s/d-hi/…"
    }
  ],
  "products": { "presence12": "https://dhi2.de/s/d-hi/…" },
  "js_url": "https://deutsches-hypnoseinstitut.de/assets/js/dhi-seminarkalender.js?v=20260727a",
  "fetched_at": "2026-08-01T03:10:04+00:00"
}
```

Ohne Auth, weil die Daten öffentlich sind: Sie stehen so im Seminarkalender der
Website und stecken ohnehin in jeder Terminantwort des Bots. Solange noch keine
Daten geladen sind, antwortet der Endpunkt mit `503`.

Genutzt wird er vom QS-Lauf der CI/CD-Pipeline
(`scripts/fetch_live_termine.py`): Der prüft, ob der Bot den frühesten
passenden Termin nennt, und braucht dafür die Solldaten. Von der Website direkt
bekommt ein GitHub-Runner sie nicht — Hostinger nimmt von Rechenzentrums-IPs
keine Verbindung an.

```bash
curl -s https://bot.example.de/api/termine | head -40
```

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
Fehlerbehandlung. Einbindung auf einer Website vor `</body>`:

```html
<script src="https://bot.example.de/widget.js"
        data-api="https://bot.example.de"
        data-desktop-bottom="96"
        data-mobile-button="off"
        defer></script>
```

### Attribute am `<script>`-Tag

| Attribut | Default | Wirkung |
|---|---|---|
| `data-api` | Origin, von dem `widget.js` geladen wurde | Basis-URL der Bot-API |
| `data-desktop-bottom` | `20` | Abstand des Chat-Buttons vom unteren Rand in px (Ganzzahl 0–400; NaN oder außerhalb des Bereichs → Default). Das Panel sitzt bei `Offset + 72 px`, seine maximale Höhe leitet sich ebenfalls ab — beides wandert also mit. |
| `data-mobile-button` | `auto` | `off`: der schwebende Button wird bei ≤ 640 px Viewport-Breite per Media Query ausgeblendet (robust gegen Rotation/Resize); das Öffnen übernimmt die Website (s. u.). Sicherheitsnetz: Findet sich kurz nach DOMContentLoaded kein `[data-dhi-chat]` im DOM, erscheint der Button mobil trotzdem. |

Alle Attribute sind optional — ohne sie verhält sich das Widget wie bisher
(Button rechts unten bei 20 px). Rechenregel für den Desktop-Offset über einem
vorhandenen Float: dessen `bottom`-Wert + dessen Höhe + 16 px Abstand
(z. B. WhatsApp-Button: 20 + 60 + 16 = 96).

### Externe Trigger: `data-dhi-chat`

Jedes Element mit dem Attribut `data-dhi-chat` (z. B. der Chat-Eintrag einer
mobilen CTA-Leiste) öffnet bzw. schließt den Chat:

```html
<a href="#chat" data-dhi-chat>Chat</a>
```

Der Klick wird per delegiertem Listener abgefangen — das funktioniert auch für
Markup, das erst nach dem Widget gerendert wird. Bei `<a>`-Elementen wird die
Navigation unterdrückt. Das Widget pflegt an den Triggern `aria-expanded` und
`aria-controls`; beim Schließen kehrt der Fokus zum auslösenden Element zurück.

### JS-API: `window.DHIBot`

```js
window.DHIBot.open();    // Chat öffnen (Fokus ins Eingabefeld, außer auf Touch)
window.DHIBot.close();   // Chat schließen (Fokus zurück zum Auslöser)
window.DHIBot.toggle();  // umschalten
window.DHIBot.version;   // z. B. "0.3.1"
```

Die Initialisierung ist idempotent — wird das Script versehentlich doppelt
eingebunden, entsteht keine zweite Instanz.

`/widget.js` wird mit `Cache-Control: public, max-age=300` ausgeliefert —
Widget-Updates erreichen Besucher binnen 5 Minuten, ohne dass das
Einbindungs-Snippet geändert werden muss.

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
