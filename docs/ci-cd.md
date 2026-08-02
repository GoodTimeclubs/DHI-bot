# CI/CD mit GitHub Actions

Automatischer Weg vom Commit zum Live-Bot: Tests → Docker-Build → Deployment
auf den VPS → Smoke-Test → QS-Testkatalog. Alles steckt in
`.github/workflows/ci-cd.yml` und den Skripten unter `scripts/`.

```
Pull Request ─┐
              ├─► Tests (pytest + Playwright) ─► Docker-Build ─┐
Push auf main ┘                                                │
                                                               ▼
                       Deployment (SSH → VPS: git reset, docker compose,
                       Health-Check, bei Fehlschlag automatischer Rollback)
                                                               │
                                                               ▼
                       Smoke-Test der Live-URL (kostenlos: Health, Index-Alter,
                       /widget.js, CORS für alle 12 Origins)
                                                               │
                                                               ▼
                       QS-Testkatalog gegen die Live-URL (kostet API-Guthaben)
```

Ein Pull Request läuft nur bis zum Docker-Build — deployt wird ausschließlich
von `main`.

---

## 1 · Server vorbereiten

> **Zuerst lesen — sonst verliert der Bot seinen Index:**
> Docker Compose leitet den Projektnamen aus dem **Verzeichnisnamen** ab, und
> daran hängen die Volumes (`…_bot_data` mit Index und Terminen, `…_caddy_data`
> mit den TLS-Zertifikaten). Wird das Verzeichnis umbenannt oder neu angelegt,
> startet der Bot mit leerem Index und Caddy holt neue Zertifikate.
> Deshalb **vor allen Änderungen** den aktuellen Projektnamen festnageln:
>
> ```bash
> docker volume ls | grep bot_data          # z.B. dhi-bot_bot_data → Projekt "dhi-bot"
> echo 'COMPOSE_PROJECT_NAME=dhi-bot' >> /pfad/zum/bot/.env
> docker compose up -d                      # prüfen: Volumes bleiben dieselben
> ```

**a) Das Verzeichnis auf dem Server muss ein Git-Klon sein.** Das Deployment
holt den Ziel-Commit per `git fetch`/`git reset --hard`. Prüfen:

```bash
cd /opt/dhi-bot && git remote -v
```

Kommt eine Fehlermeldung, den Bestand einmalig auf einen Klon umstellen — die
`.env` ist nicht im Repo und muss übernommen werden:

```bash
cd /opt
cp dhi-bot/.env ~/dhi-bot.env.sicherung          # Sicherheitskopie
mv dhi-bot dhi-bot-alt
git clone https://github.com/GoodTimeclubs/DHI-bot.git dhi-bot
cp dhi-bot-alt/.env dhi-bot/.env                 # COMPOSE_PROJECT_NAME nicht vergessen
cd dhi-bot && docker compose up -d
```

Das Repo ist öffentlich, ein Deploy-Key für GitHub ist deshalb nicht nötig.
(Wird es später privat, braucht der Server einen eigenen Read-only-Deploy-Key.)

**b) Benutzer für das Deployment.** Am einfachsten der Benutzer, mit dem du
dich ohnehin einloggst (bei STRATO meist `root`) — dann ist hier nichts zu tun.
Sauberer, aber optional, ist ein eigener Benutzer in der `docker`-Gruppe:

```bash
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
chown -R deploy:deploy /opt/dhi-bot
```

**c) SSH-Schlüssel nur für die Pipeline.** Zweck: GitHub muss sich auf dem VPS
einloggen können, ohne ein Passwort eingeben zu können. Also ein Schlüsselpaar
erzeugen, die öffentliche Hälfte auf den Server legen, die private als
GitHub-Secret hinterlegen. Bei der Passphrase-Abfrage **zweimal Enter** —
der Schlüssel muss ohne Passphrase sein. `<benutzer>@<server>` ist das, womit
du dich sonst einloggst (z.B. `root@bot.deutsches-hypnoseinstitut.de`).

*Windows — PowerShell; der OpenSSH-Client steckt in Windows 10/11, auch wenn du
sonst PuTTY nutzt:*

```powershell
# 1 · Schlüsselpaar erzeugen (zweimal Enter bei der Passphrase)
ssh-keygen -t ed25519 -C "github-actions-dhi-bot" -f $env:USERPROFILE\.ssh\dhi-deploy

# 2 · öffentliche Hälfte an die authorized_keys des Servers hängen
#     (hier fragt er einmal nach dem Server-Passwort — das ist normal)
type $env:USERPROFILE\.ssh\dhi-deploy.pub | ssh <benutzer>@<server> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

# 3 · Probe — muss OHNE Passwortabfrage durchlaufen
ssh -i $env:USERPROFILE\.ssh\dhi-deploy <benutzer>@<server> "docker compose version"

# 4 · private Hälfte für das Secret VPS_SSH_KEY in die Zwischenablage
type $env:USERPROFILE\.ssh\dhi-deploy | clip
```

*macOS/Linux:*

```bash
ssh-keygen -t ed25519 -C "github-actions-dhi-bot" -f ~/.ssh/dhi-deploy -N ""
ssh-copy-id -i ~/.ssh/dhi-deploy.pub <benutzer>@<server>
ssh -i ~/.ssh/dhi-deploy <benutzer>@<server> "docker compose version"
```

Schritt 3 ist der eigentliche Test: Läuft er ohne Passwort durch, funktioniert
später auch die Pipeline. Die Datei **mit** `.pub` gehört auf den Server, die
**ohne** ausschließlich ins GitHub-Secret. Läuft auf dem Server fail2ban oder
eine Firewall, die SSH auf die eigene IP begrenzt: GitHub-Runner haben
wechselnde IPs, der Zugang muss also offen sein (oder ein selbst gehosteter
Runner übernehmen).

**d) Hostschlüssel notieren** (verhindert, dass sich die Pipeline blind mit
irgendeinem Server verbindet). Die komplette Ausgabe kommt in das Secret
`VPS_KNOWN_HOSTS`:

```bash
ssh-keyscan -t ed25519,rsa <server>
```

---

## 2 · Secrets und Variablen in GitHub

**Settings → Environments → New environment → `production`**, dort unter
*Environment secrets*:

| Secret | Beispiel | |
|---|---|---|
| `VPS_HOST` | `bot.deutsches-hypnoseinstitut.de` | Server, per SSH erreichbar |
| `VPS_USER` | `deploy` | |
| `VPS_SSH_KEY` | Inhalt von `~/.ssh/dhi-deploy` | **privater** Schlüssel, mit `-----BEGIN…`- und `-----END…`-Zeile |
| `VPS_KNOWN_HOSTS` | Ausgabe von `ssh-keyscan` | |
| `VPS_PORT` | `22` | optional, nur bei abweichendem Port |
| `QS_TEST_TOKEN` | derselbe Wert wie `TEST_TOKEN` in der Server-`.env` | trennt den QS-Lauf vom Produktivguthaben (Abschnitt 5) |

**Settings → Secrets and variables → Actions → Variables** (optional, alles hat
sinnvolle Vorgaben):

| Variable | Vorgabe | |
|---|---|---|
| `VPS_APP_DIR` | `/opt/dhi-bot` | Verzeichnis auf dem Server |
| `BOT_URL` | `https://bot.deutsches-hypnoseinstitut.de` | Ziel von Smoke-Test und QS |
| `QS_UMFANG` | `voll` | `voll` (49 Fälle) · `smoke` (15 Fälle) · `aus` |

Im Environment `production` lässt sich zusätzlich unter *Required reviewers*
eine Freigabe erzwingen — dann wartet jedes Deployment auf einen Klick.

---

## 3 · Erster Lauf

Am besten mit einem harmlosen Commit (z.B. dieser Doku) auf `main` — oder
**Actions → CI/CD → Run workflow** mit `qs_umfang: smoke`, um das erste
Deployment ohne den vollen API-Verbrauch zu prüfen.

Zu sehen ist danach:

- **Tests** — 49 Unit-/Playwright-Tests, komplett offline aus `fixtures/`
- **Deployment** — der Commit auf dem Server, Build, Neustart, Health-Check
- **Smoke-Test** — Health, Index-Alter, `/widget.js`, CORS je Origin, dazu ein
  Hinweis, auf welchen Domains das Widget-Snippet fehlt
- **QS** — Ergebnistabelle in der Job-Zusammenfassung, Volltext im Artefakt
  `qs-bericht`

---

## 4 · Rollback

**Actions → CI/CD → Run workflow**, bei `deploy_sha` den letzten
funktionierenden Commit eintragen (z.B. `5f4ae34`). Das Deployment rollt
genau diesen Stand aus.

Automatisch passiert das ohnehin schon: Antwortet der frisch gestartete
Container nicht binnen ~90 Sekunden mit `status: ok`, setzt
`scripts/deploy_remote.sh` den Server auf den vorherigen Commit zurück, baut
neu und meldet das Deployment als gescheitert. Die letzten 60 Log-Zeilen des
Containers stehen dann im Actions-Log.

Von Hand auf dem Server geht es genauso:

```bash
cd /opt/dhi-bot && git reset --hard <commit> && docker compose up -d --build
```

---

## 5 · Was das kostet

Der QS-Testkatalog stellt echte Chat-Anfragen an den Live-Bot. Nachgerechnet
am Lauf vom 02.08.2026 (59 Fälle, davon 6 deterministisch aus `termine.py`
beantwortet und damit kostenlos → **53 API-Anfragen**):

| | |
|---|---|
| System-Prompt je Anfrage | ~29.600 Zeichen ≈ **8.500 Token** (Regeln, TERMINDATEN, PREISDATEN, KLARSTELLUNGEN, 6 Website-Auszüge) |
| Antworten, alle 53 zusammen | ~27.900 Zeichen ≈ 8.000 Token |
| Input × $1/MTok | ~$0,45 |
| Output × $5/MTok | ~$0,04 |
| **Volllauf gesamt** | **≈ US$ 0,50** (Spanne 0,45–0,56 je nach Tokenisierung) |
| Smoke-Umfang (15 Fälle, 12 davon per API) | ≈ US$ 0,11 |
| Nachprüfung einzelner Fälle via `ONLY` (10 Fälle) | ≈ US$ 0,09 |

Rund 92 % davon ist der System-Prompt, der bei jeder Anfrage komplett neu
bezahlt wird. Zum Vergleich der Live-Betrieb: eine Besucher-Nachricht kostet
nach derselben Rechnung **rund 1 US-Cent** — bei `DAILY_MESSAGE_LIMIT=1000`
sind das im Extremfall ~9 US$ an einem Tag.

Die Token-Zahlen sind aus Zeichenlängen hochgerechnet (deutscher Text, 3,2–3,8
Zeichen je Token); der exakte Verbrauch steht in der Anthropic Console unter
Usage.

Das ist der Punkt, an dem die Pipeline mit dem offenen ToDo „API-Guthaben"
kollidiert: Am 01.08.2026 lagen **US$ 0,07** auf dem Konto. In dem Zustand
kann schon ein einziger Volllauf das Guthaben aufbrauchen — und dann
antwortet der **Live-Bot auf allen Domains nicht mehr**. Also erst
automatisches Aufladen und ein Spend-Limit einrichten, und bis dahin
`QS_UMFANG=aus` oder `smoke` setzen.

Wer den Volllauf billiger will: Der System-Prompt ist bis zum Block
WEBSITE-AUSZÜGE bei jeder Anfrage identisch. Ein Cache-Breakpoint davor
(Prompt-Caching, Cache-Treffer kosten 10 % des Input-Preises) würde den
Volllauf grob halbieren. Für den Live-Betrieb lohnt sich das dagegen nur bei
dichtem Verkehr — bei verstreuten Besucheranfragen läuft der Cache ab, und
Cache-Schreibvorgänge kosten 25 % mehr als normaler Input.

### Getrennter API-Schlüssel für QS-Läufe

Damit ein Testlauf nie das Guthaben aufbraucht, aus dem echte Besucher bedient
werden, läuft der Katalog über einen **zweiten Anthropic-Schlüssel**. Drei
Schritte, einmalig:

1. In der Anthropic Console einen zweiten API-Key anlegen (eigenes Spend-Limit
   setzen — das ist der eigentliche Schutz) und ein Passwort für den Zugang
   würfeln: `openssl rand -hex 24`
2. Auf dem VPS in die `.env`, danach `docker compose up -d`:

   ```bash
   ANTHROPIC_API_KEY_TEST=sk-ant-…      # zweiter Key, eigenes Guthaben
   TEST_TOKEN=<gewürfelter Wert>        # Zugang zum Testpfad
   ```

3. Denselben `TEST_TOKEN`-Wert als Environment-Secret **`QS_TEST_TOKEN`** in
   GitHub hinterlegen.

Wie es funktioniert: Der Testrunner schickt den Header `X-DHI-Test: <TEST_TOKEN>`.
Anfragen mit gültigem Token beantwortet der Bot über den zweiten Schlüssel,
zählt sie getrennt (`test_messages_today` in `/api/health`) und nimmt sie von
`DAILY_MESSAGE_LIMIT` **und** vom IP-Rate-Limit aus. Letzteres ist der zweite
Gewinn: **Ohne Rate-Limit braucht der Katalog keine Blöcke und keine Pausen** —
59 Fälle laufen in gut einer Minute statt in einer Viertelstunde
(`scripts/qs_live.sh` schaltet automatisch um, sobald `DHI_TEST_TOKEN` gesetzt ist).

Zwei bewusste Härten, damit die Trennung nicht stillschweigend kippt: Ein
falscher Token wird mit `403` abgewiesen, statt auf den Produktivpfad
zurückzufallen. Und ein gültiger Token ohne konfigurierten Zweitschlüssel
liefert `503` statt einer Antwort auf Produktivkosten. Fehlt das Secret ganz,
warnen Runner und Skript im Log — der Lauf geht dann wie bisher aufs
Produktivguthaben. Der Smoke-Test meldet den Zustand als Hinweis mit
(`test_key_configured` in `/api/health`).

Alles andere ist kostenlos: GitHub Actions ist für öffentliche Repos
unbegrenzt frei, der Smoke-Test schickt keine Chat-Anfrage.

---

## 6 · Warum der QS-Lauf in Blöcken läuft

Der Bot lässt **20 Chat-Anfragen je 5 Minuten und IP** zu (`_rate_ok` in
`app/main.py`). Hinter Caddy zählt mit `TRUST_PROXY=1` der **letzte** Eintrag
in `X-Forwarded-For` — den setzt Caddy selbst auf die echte Absender-IP. Die
IP-Rotation des Testrunners läuft dort also ins Leere (daher `--no-xff`), und
ein Runner ist genau eine IP.

`scripts/qs_live.sh` teilt den Katalog deshalb in Blöcke zu 18 Fällen mit
310 Sekunden Pause. Über `BLOCK`, `PAUSE` und `WORKERS` lässt sich das
anpassen, wenn sich das Rate-Limit ändert.

**Mit gesetztem `DHI_TEST_TOKEN` entfällt das komplett:** QS-Anfragen sind vom
Rate-Limit ausgenommen (siehe Abschnitt 5), das Skript schaltet dann von selbst
auf einen Block ohne Pause um.

Einzelne Fälle nachprüfen, ohne den ganzen Katalog zu bezahlen — z.B. nach
einer Prompt-Änderung nur die zuletzt gescheiterten Fälle (Präfix-Match,
`H1` nimmt also auch `H10` mit):

```bash
BASE_URL=https://bot.deutsches-hypnoseinstitut.de \
ONLY=C4,C5,C8,C9,E3,F5,H1,H2,H3 bash scripts/qs_live.sh
```

### Woher die Solldaten für die Terminprüfungen kommen

Der Katalog prüft unter anderem, ob der Bot den frühesten passenden Termin
nennt — dafür braucht der Runner die Termine selbst. Die direkt von
`deutsches-hypnoseinstitut.de` zu holen **funktioniert aus GitHub Actions
nicht**: Der Runner bekommt keine Verbindung (Zeitüberschreitung, kein 403 —
Hostinger nimmt von Rechenzentrums-IPs offenbar nichts an; die Website liegt
dort, der Bot dagegen bei STRATO und ist problemlos erreichbar).

`scripts/fetch_live_termine.py` holt sie deshalb über **`GET /api/termine`**
vom Bot. Das ist auch inhaltlich der bessere Weg: Geprüft wird gegen genau die
Termine, die der Bot kennt — sonst meldete der Katalog Fehler, die nur daran
liegen, dass der nächtliche Crawl eine Kalenderänderung noch nicht aufgenommen
hat. Dass der Datenstand frisch ist, prüft der Smoke-Test getrennt über das
Index-Alter.

Aus demselben Grund kann der Smoke-Test aus Actions heraus **nicht** sehen, ob
das Widget-Snippet auf den Websites eingebunden ist; er meldet die Domains
gesammelt als „nicht prüfbar". Aussagekräftig wird dieser Teil, wenn du das
Skript von einem normalen Anschluss aus laufen lässt:

```bash
python scripts/smoke_live.py --base-url https://bot.deutsches-hypnoseinstitut.de
```

---

## 7 · Wenn etwas klemmt

| Meldung | Ursache |
|---|---|
| `Arbeitsverzeichnis auf dem Server ist nicht sauber` | Auf dem VPS wurde eine versionierte Datei von Hand geändert (z.B. `Caddyfile`). Das Deployment bricht bewusst ab, statt sie zu überschreiben: Änderung ins Repo übernehmen oder mit `git checkout -- <Datei>` verwerfen. |
| `Permission denied (publickey)` | Öffentlicher Schlüssel liegt nicht in `~/.ssh/authorized_keys` des Deploy-Users, oder `VPS_SSH_KEY` wurde ohne die `BEGIN`/`END`-Zeilen eingefügt. |
| `Host key verification failed` | `VPS_KNOWN_HOSTS` fehlt oder passt nicht mehr (Server neu aufgesetzt) — `ssh-keyscan` erneut ausführen. |
| Smoke-Test meldet `CORS <subdomain>` | Die Origin fehlt in `ALLOWED_ORIGINS` auf dem Server. Genau dafür ist die Prüfung da — dort schweigt der Chat sonst unbemerkt. |
| Smoke-Test meldet `Index jünger als 36 h` als Fehler | Der nächtliche Re-Crawl um 03:10 Uhr ist gescheitert; der Bot antwortet mit veralteten Inhalten weiter. |
| `mock_mode: true` im Smoke-Test | Auf dem Server fehlt der `ANTHROPIC_API_KEY` in der `.env` — oder das Guthaben ist leer. |
| QS-Fälle scheitern mit HTTP 429 | Rate-Limit: `BLOCK` verkleinern oder `PAUSE` erhöhen. |
| `/api/termine` antwortet mit `404` | Auf dem Server läuft noch ein Stand vor v0.3.2. Erst deployen, dann QS — in einem Push passiert genau das automatisch in dieser Reihenfolge. |
| `/api/termine` antwortet mit `503` | Der Bot hat noch keine Daten geladen (frischer Container mit leerem Volume). Ein paar Minuten warten, bis der erste Crawl durch ist. |

---

## 8 · Badge für die README

```markdown
[![CI/CD](https://github.com/GoodTimeclubs/DHI-bot/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/GoodTimeclubs/DHI-bot/actions/workflows/ci-cd.yml)
```

---

## 9 · Was die Pipeline bewusst **nicht** anfasst

- die `.env` auf dem Server (Produktivkonfiguration, nicht im Repo)
- die Volumes `bot_data` (Index, Termine) und `caddy_data` (Zertifikate)
- den täglichen Re-Crawl um 03:10 Uhr — der läuft weiter im Container
- die Website des Instituts (Widget-Snippet) — die liegt bei Hostinger und
  wird nur geprüft, nicht verändert
