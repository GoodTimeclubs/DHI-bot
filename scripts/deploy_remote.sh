#!/usr/bin/env bash
# DHI Bot — Deployment auf dem VPS
# ────────────────────────────────────────────────────────────────────────────
# Wird von GitHub Actions per SSH über stdin hineingereicht und dort ausgeführt:
#
#     ssh vps "bash -s -- <COMMIT-SHA> <APP_DIR>" < scripts/deploy_remote.sh
#
# Ablauf: Vorzustand sichern → auf den Ziel-Commit synchronisieren →
#         Image bauen → Container neu starten → Health-Check im Container →
#         bei Fehlschlag automatisch auf den Vorzustand zurückrollen.
#
# Bewusst unangetastet bleiben:
#   • .env         — die Produktivkonfiguration liegt NUR auf dem Server
#                    (nicht im Repo, git reset fasst ignorierte Dateien nicht an)
#   • bot_data     — Docker-Volume mit Index und Termindaten, überlebt den
#                    Container-Neubau; deshalb kein Crawl beim Start nötig
#   • caddy_data   — Let's-Encrypt-Zertifikate
set -Eeuo pipefail

SHA="${1:?Ziel-Commit fehlt (Aufruf: bash -s -- <SHA> <APP_DIR>)}"
APP_DIR="${2:-/opt/dhi-bot}"
HEALTH_VERSUCHE="${HEALTH_VERSUCHE:-45}"   # × 2 s ≈ 90 s Anlaufzeit

log()  { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
fehl() { printf '\033[31m!! %s\033[0m\n' "$*" >&2; }

# ── Vorprüfungen ────────────────────────────────────────────────────────────
cd "$APP_DIR" 2>/dev/null || { fehl "Verzeichnis $APP_DIR existiert nicht."; exit 1; }
[ -d .git ]              || { fehl "$APP_DIR ist kein Git-Repo — siehe docs/ci-cd.md, Abschnitt 'Server vorbereiten'."; exit 1; }
[ -f docker-compose.yml ]|| { fehl "docker-compose.yml fehlt in $APP_DIR."; exit 1; }
[ -f .env ]              || { fehl ".env fehlt in $APP_DIR — ohne Produktivkonfiguration wird nicht deployt."; exit 1; }

if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  fehl "Docker Compose ist auf dem Server nicht verfügbar."; exit 1
fi

# Von Hand geänderte, versionierte Dateien? Dann lieber abbrechen als
# überschreiben — sonst gehen Server-Anpassungen unbemerkt verloren.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  fehl "Arbeitsverzeichnis auf dem Server ist nicht sauber:"
  git status --short --untracked-files=no >&2
  fehl "Deployment abgebrochen, es wurde nichts verändert."
  fehl "Änderungen entweder ins Repo übernehmen oder mit 'git checkout -- <Datei>' verwerfen."
  exit 1
fi

VORHER="$(git rev-parse HEAD)"
log "Deployment: $VORHER → $SHA   (Verzeichnis: $APP_DIR)"

# ── Health-Check im Container ───────────────────────────────────────────────
# Der Bot veröffentlicht keine Ports (nur Caddy ist von außen erreichbar),
# deshalb wird von innen geprüft. httpx steckt bereits im Image.
health() {
  $DC exec -T dhi-bot python -c "
import json, sys, httpx
try:
    r = httpx.get('http://127.0.0.1:8080/api/health', timeout=5)
    d = r.json()
except Exception as e:
    print('noch nicht bereit:', type(e).__name__); sys.exit(1)
print(json.dumps(d, ensure_ascii=False))
sys.exit(0 if r.status_code == 200 and d.get('status') == 'ok' else 1)
" 2>&1
}

warte_auf_health() {
  local i ausgabe
  for ((i = 1; i <= HEALTH_VERSUCHE; i++)); do
    if ausgabe="$(health)"; then
      echo "$ausgabe"
      return 0
    fi
    sleep 2
  done
  echo "${ausgabe:-keine Antwort}"
  return 1
}

hochfahren() {
  $DC build --pull
  $DC up -d --remove-orphans
}

# ── Ausrollen ───────────────────────────────────────────────────────────────
log "Repo auf den Ziel-Commit bringen"
git fetch --quiet origin
git checkout --quiet main 2>/dev/null || git checkout --quiet -B main
git reset --hard --quiet "$SHA" || { fehl "Commit $SHA nicht gefunden (schon gepusht?)."; exit 1; }
git --no-pager log -1 --format='  %h  %s  (%an, %ad)' --date=short

log "Image bauen und Container starten"
hochfahren

log "Health-Check"
if warte_auf_health; then
  log "Deployment erfolgreich"
  docker image prune -f >/dev/null 2>&1 || true
  exit 0
fi

# ── Rollback ────────────────────────────────────────────────────────────────
fehl "Health-Check fehlgeschlagen — Rollback auf $VORHER"
$DC logs --tail 60 dhi-bot 2>&1 | sed 's/^/    /' || true
git reset --hard --quiet "$VORHER"
hochfahren
if warte_auf_health; then
  fehl "Rollback erfolgreich: der Bot läuft wieder auf $VORHER. Das Deployment gilt als fehlgeschlagen."
else
  fehl "ACHTUNG: Auch nach dem Rollback antwortet der Bot nicht — bitte sofort von Hand auf den Server schauen."
fi
exit 1
