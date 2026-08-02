#!/usr/bin/env bash
# DHI Bot — QS-Testkatalog gegen den Live-Bot
# ────────────────────────────────────────────────────────────────────────────
# Spielt tests/testkatalog.yaml gegen die produktive URL — in Blöcken, weil
# der Bot pro IP nur 20 Chat-Anfragen je 5 Minuten annimmt (app/main.py,
# _rate_ok). Ein GitHub-Runner ist genau eine IP, und hinter Caddy zählt die
# echte Runner-IP (TRUST_PROXY=1) — die X-Forwarded-For-Rotation des Runners
# greift dort also nicht, deshalb --no-xff.
#
# ACHTUNG: Jeder Fall ist eine echte Claude-Anfrage und kostet Guthaben.
#
#   BASE_URL=https://bot.deutsches-hypnoseinstitut.de UMFANG=voll bash scripts/qs_live.sh
#
# UMFANG=voll   → alle 49 Fälle, 3 Blöcke, ca. 12 Minuten
# UMFANG=smoke  → 15 besonders fehleranfällige Fälle, 1 Block, ca. 1 Minute
set -Eeuo pipefail

BASE_URL="${BASE_URL:?BASE_URL fehlt}"
UMFANG="${UMFANG:-voll}"
BLOCK="${BLOCK:-18}"        # unter dem Limit von 20 Anfragen / 5 Min / IP
PAUSE="${PAUSE:-310}"       # Zeitfenster 300 s + Puffer
WORKERS="${WORKERS:-4}"
OUT_DIR="${OUT_DIR:-tests/report}"

cd "$(dirname "$0")/.."
mkdir -p "$OUT_DIR"

mapfile -t BLOECKE < <(UMFANG="$UMFANG" BLOCK="$BLOCK" python3 - <<'PY'
import os, yaml

# Kleine Auswahl für schnelle Läufe: die Fälle, die in den QS-Runden am
# häufigsten gekippt sind (Preisfallen, früheste Termine, Anrede, Abgrenzung
# Ausbildung/Behandlung, Prompt-Injection).
SMOKE = ["B1", "B2", "B7", "C1", "C2", "C6", "C9", "D2",
         "E1", "E3", "E6", "F3", "F7", "G1", "G2"]

umfang = os.environ["UMFANG"]
block = int(os.environ["BLOCK"])
faelle = yaml.safe_load(open("tests/testkatalog.yaml", encoding="utf-8"))["faelle"]
ids = [f["id"] for f in faelle]
if umfang == "smoke":
    ids = [i for i in ids if i.split("-")[0] in SMOKE]
for i in range(0, len(ids), block):
    print(",".join(ids[i:i + block]))
PY
)

anzahl_bloecke=${#BLOECKE[@]}
[ "$anzahl_bloecke" -gt 0 ] || { echo "!! Keine Testfälle ausgewählt (UMFANG=$UMFANG)"; exit 1; }

echo "QS-Testkatalog ($UMFANG) gegen $BASE_URL — $anzahl_bloecke Block/Blöcke à max. $BLOCK Fälle"

fehler=0
for i in "${!BLOECKE[@]}"; do
  if [ "$i" -gt 0 ]; then
    echo "… Pause ${PAUSE}s (Rate-Limit: 20 Anfragen / 5 Min pro IP)"
    sleep "$PAUSE"
  fi
  echo ""
  echo "▶ Block $((i + 1))/$anzahl_bloecke"
  if ! python3 tests/run_testkatalog.py \
        --base-url "$BASE_URL" \
        --only "${BLOECKE[$i]}" \
        --no-xff \
        --workers "$WORKERS" \
        --out "$OUT_DIR/ci-block-$((i + 1))"; then
    fehler=$((fehler + 1))
  fi
done

# Kurzfassung in die GitHub-Zusammenfassung schreiben
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    if [ "$fehler" -eq 0 ]; then
      echo "## ✅ QS-Testkatalog ($UMFANG) bestanden"
    else
      echo "## ❌ QS-Testkatalog ($UMFANG): $fehler von $anzahl_bloecke Blöcken mit Fehlern"
    fi
    echo ""
    echo "Server: \`$BASE_URL\` · Details im Artefakt **qs-bericht**"
    echo ""
    grep -h '^\*\*Ergebnis' "$OUT_DIR"/ci-block-*.md 2>/dev/null | sed 's/^/- /' || true
  } >> "$GITHUB_STEP_SUMMARY"
fi

[ "$fehler" -eq 0 ] || {
  echo ""
  echo "!! QS-Lauf mit Fehlern beendet — Bericht: $OUT_DIR/ci-block-*.md"
  exit 1
}
echo ""
echo "✓ QS-Lauf ohne Fehler"
