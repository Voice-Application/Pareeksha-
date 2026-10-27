# Shared by the verify steps. A step prints its evidence into proof/verify/V<n>.md and exits:
#   0 PASS   1 FAIL   2 PENDING (needs an input only the owner can provide; counts as not passed)
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
COMPOSE=${COMPOSE:-docker compose}
export COMPOSE
OUT="$ROOT/proof/verify"
mkdir -p "$OUT"
PY=${PYTHON:-python3}

# begin <n> <title> : start the evidence file
begin() { STEP=$1; EVID="$OUT/V$1.md"; printf '# V%s: %s\n\nRun at %s on commit %s\n\n' "$1" "$2" "$(date -u +%FT%TZ)" "$(git -C "$ROOT" rev-parse --short HEAD)" > "$EVID"; }
note() { printf '%s\n' "$*" >> "$EVID"; }
block() { { printf '```\n'; cat; printf '```\n'; } >> "$EVID"; }
# finish PASS|FAIL|PENDING <reason>
finish() {
  printf '\nSTATUS: %s\nREASON: %s\n' "$1" "$2" >> "$EVID"
  echo "$1 V$STEP: $2 (evidence: proof/verify/V$STEP.md)"
  case $1 in PASS) exit 0 ;; PENDING) exit 2 ;; *) exit 1 ;; esac
}
api_port() { grep -E '^API_HOST_PORT=' "$ROOT/.env" 2>/dev/null | cut -d= -f2 | cut -d' ' -f1 || true; }
API="${PAREEKSHA_API_URL:-http://localhost:$(api_port | grep . || echo 8000)/api/v1}"
export PAREEKSHA_API_URL="$API"
psql_q() { $COMPOSE exec -T postgres psql -U pareeksha -d pareeksha -At -c "$1"; }
