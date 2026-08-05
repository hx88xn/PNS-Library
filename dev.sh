#!/usr/bin/env bash
#
# Run PDAS for development: backend, then the Electron client with hot reload.
#
#   ./dev.sh            backend + client
#   ./dev.sh backend    backend only
#   ./dev.sh check      report what is running and what is indexed
#
# Reads .env in the repo root if present, so local model and port choices live
# in one place instead of in your shell history.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/backend/.venv"

[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }

: "${PDAS_OLLAMA_HOST:=http://127.0.0.1:11434}"
: "${PDAS_LLM_MODEL:=qwen3.5:4b}"
: "${PDAS_EMBED_MODEL:=bge-m3}"
: "${PDAS_DATA_DIR:=$ROOT/backend/var}"
: "${PDAS_PORT:=8000}"
export PDAS_OLLAMA_HOST PDAS_LLM_MODEL PDAS_EMBED_MODEL PDAS_DATA_DIR PDAS_PORT

MODE="${1:-all}"

die() { echo "  $1" >&2; exit 1; }

# ── Preconditions ────────────────────────────────────────────────────────
[[ -x "$VENV/bin/pdas" ]] || die "No venv. Run: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.in && .venv/bin/pip install -e ."

if ! curl -sf --max-time 3 "$PDAS_OLLAMA_HOST/api/tags" >/dev/null; then
  die "Ollama unreachable at $PDAS_OLLAMA_HOST — start it with: ollama serve"
fi

AVAILABLE="$(curl -s --max-time 5 "$PDAS_OLLAMA_HOST/api/tags" | tr ',' '\n' | grep -o '"name":"[^"]*"' | cut -d'"' -f4)"
for model in "$PDAS_LLM_MODEL" "$PDAS_EMBED_MODEL"; do
  want="$model"; [[ "$want" == *:* ]] || want="$want:latest"
  grep -qx "$want" <<<"$AVAILABLE" || {
    echo "  '$model' is not pulled at $PDAS_OLLAMA_HOST" >&2
    echo "  available: $(tr '\n' ' ' <<<"$AVAILABLE")" >&2
    exit 1
  }
done

# ── check ────────────────────────────────────────────────────────────────
if [[ "$MODE" == "check" ]]; then
  echo "Ollama    $PDAS_OLLAMA_HOST"
  echo "LLM       $PDAS_LLM_MODEL"
  echo "Embed     $PDAS_EMBED_MODEL"
  echo "Data dir  $PDAS_DATA_DIR"
  "$VENV/bin/pdas" status
  exit 0
fi

# ── Run ──────────────────────────────────────────────────────────────────
echo "PDAS dev"
echo "  ollama    $PDAS_OLLAMA_HOST"
echo "  llm       $PDAS_LLM_MODEL"
echo "  backend   http://127.0.0.1:$PDAS_PORT"
echo

# Warm both models and pin them in memory. Ollama's default keep_alive is five
# minutes, so the first request after a pause pays a cold load — measured at
# ~2s for bge-m3 and longer for the LLM, which reads as the app being slow
# rather than the model being unloaded.
echo "  warming models (first run loads ~4 GB)…"
for model in "$PDAS_EMBED_MODEL" "$PDAS_LLM_MODEL"; do
  curl -sf --max-time 180 "$PDAS_OLLAMA_HOST/api/generate" \
    -d "{\"model\":\"$model\",\"prompt\":\"\",\"keep_alive\":\"8h\"}" >/dev/null 2>&1 || true
done

cleanup() { [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null; }
trap cleanup EXIT INT TERM

"$VENV/bin/pdas" serve --port "$PDAS_PORT" &
BACKEND_PID=$!

for _ in $(seq 30); do
  curl -sf --max-time 2 "http://127.0.0.1:$PDAS_PORT/api/health" >/dev/null && break
  sleep 1
done

STATUS="$(curl -s --max-time 5 "http://127.0.0.1:$PDAS_PORT/api/health")" || STATUS=""
if [[ -z "$STATUS" ]]; then
  echo "  backend did not come up" >&2
  exit 1
fi
grep -q '"status":"ok"' <<<"$STATUS" \
  && echo "  health    ok" \
  || echo "  health    degraded — $(grep -o '"problems":\[[^]]*\]' <<<"$STATUS")"

if [[ "$MODE" == "backend" ]]; then
  echo
  echo "  Backend only. Ctrl-C to stop."
  wait "$BACKEND_PID"
  exit 0
fi

echo
[[ -d "$ROOT/node_modules" ]] || { echo "  installing frontend deps…"; (cd "$ROOT" && npm install --silent); }
cd "$ROOT" && npm run dev
