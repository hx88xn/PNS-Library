#!/usr/bin/env bash
#
# Fetch the Ollama runtime and the two models, ready to carry onto the
# air-gapped server.
#
# RUN THIS ON A CONNECTED LINUX MACHINE. Ollama does NOT need to be installed:
# the script downloads the runtime, extracts it to a temporary directory, and
# uses that binary to pull. Nothing is installed system-wide, no service
# account is created, and the client doing the pull is by construction the same
# version the server will run.
#
#   ./deploy/fetch_models.sh [output_dir]
#
# Needs zstd (`apt-get install zstd`) if tar lacks --zstd support.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/offline/ollama}"

LLM_MODEL="${PDAS_LLM_MODEL:-qwen3.5:4b}"
EMBED_MODEL="${PDAS_EMBED_MODEL:-bge-m3}"
OLLAMA_VERSION="${OLLAMA_VERSION:-}"   # empty = latest

mkdir -p "$OUT"

# ── 1. The runtime ───────────────────────────────────────────────────────
# Asset is ollama-linux-amd64.tar.zst (~1.4 GB, CUDA libraries included), NOT
# the .tgz that older documentation refers to — that URL now 404s. Resolve the
# name from the release API rather than hardcoding it, so a future rename fails
# here on a connected machine instead of halfway through a transfer.
ASSET="ollama-linux-amd64.tar.zst"
TARBALL="$OUT/$ASSET"

if [[ -f "$TARBALL" ]]; then
  echo "Runtime already downloaded: $TARBALL"
else
  if [[ -n "$OLLAMA_VERSION" ]]; then
    RELEASE_API="https://api.github.com/repos/ollama/ollama/releases/tags/${OLLAMA_VERSION}"
  else
    RELEASE_API="https://api.github.com/repos/ollama/ollama/releases/latest"
  fi

  URL="$(curl -fsSL "$RELEASE_API" \
        | grep -o "https://[^\"]*/${ASSET}" | head -1)"

  if [[ -z "$URL" ]]; then
    echo "Could not find $ASSET in the release. Assets available:" >&2
    curl -fsSL "$RELEASE_API" | grep -o '"name": "[^"]*"' | cut -d'"' -f4 >&2
    exit 1
  fi

  echo "Downloading runtime: $URL"
  curl -fL --progress-bar "$URL" -o "$TARBALL"

  # Ollama publishes checksums for its own assets; use them.
  SUMS_URL="${URL%/*}/sha256sum.txt"
  if curl -fsSL "$SUMS_URL" -o "$OUT/ollama-sha256sum.txt" 2>/dev/null; then
    EXPECTED="$(grep " .*${ASSET}\$" "$OUT/ollama-sha256sum.txt" | awk '{print $1}' | head -1)"
    ACTUAL="$(sha256sum "$TARBALL" | awk '{print $1}')"
    if [[ -n "$EXPECTED" && "$EXPECTED" != "$ACTUAL" ]]; then
      echo "Runtime checksum mismatch — download is corrupt." >&2
      exit 1
    fi
    echo "  runtime checksum verified"
  fi
fi

# ── 2. Pull with the runtime we just downloaded ──────────────────────────
# Deliberately NOT `curl https://ollama.com/install.sh | sh`. That creates a
# service account, a systemd unit and a background daemon on a machine whose
# only job is downloading files. Using the shipped binary instead also
# guarantees the client doing the pull is the exact version the server will
# run — an older client gets "412: requires a newer version of Ollama" on
# recent models, which is a confusing way to lose an afternoon.
WORK="$(mktemp -d)"
trap 'kill "${SERVER_PID:-}" 2>/dev/null || true; rm -rf "$WORK"' EXIT

echo
echo "Extracting the runtime (no system install)…"
if tar --zstd -tf "$TARBALL" >/dev/null 2>&1; then
  tar --zstd -xf "$TARBALL" -C "$WORK"
elif command -v unzstd >/dev/null; then
  unzstd -c "$TARBALL" | tar -xf - -C "$WORK"
else
  echo "zstd support is missing. apt-get install zstd" >&2
  exit 1
fi

OLLAMA_BIN="$(find "$WORK" -type f -name ollama -perm -u+x | head -1)"
[[ -n "$OLLAMA_BIN" ]] || { echo "No ollama binary inside $TARBALL" >&2; exit 1; }
echo "  $("$OLLAMA_BIN" --version 2>/dev/null | head -1)"

# Pull straight into the bundle. No copying afterwards, and nothing to hunt
# for: the store is exactly where it needs to be.
export OLLAMA_MODELS="$OUT/models"
export OLLAMA_HOST="127.0.0.1:${OLLAMA_FETCH_PORT:-11439}"
mkdir -p "$OLLAMA_MODELS"

"$OLLAMA_BIN" serve >"$WORK/serve.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 30); do
  "$OLLAMA_BIN" list >/dev/null 2>&1 && break
  sleep 1
done
"$OLLAMA_BIN" list >/dev/null 2>&1 || {
  echo "The runtime did not start. Log:" >&2
  tail -20 "$WORK/serve.log" >&2
  exit 1
}

for model in "$EMBED_MODEL" "$LLM_MODEL"; do
  echo
  echo "Pulling $model"
  "$OLLAMA_BIN" pull "$model"
done

CLIENT_VERSION="$("$OLLAMA_BIN" --version 2>/dev/null | head -1)"
kill "$SERVER_PID" 2>/dev/null || true
unset SERVER_PID

# ── 3. Verify the store ──────────────────────────────────────────────────
# Content-addressed: blobs/ holds the weights, manifests/ maps tags to them.
# A store with manifests and no blobs installs cleanly and fails at first use,
# which is a miserable thing to discover on the server.
BLOB_COUNT="$(find "$OUT/models/blobs" -type f 2>/dev/null | wc -l)"
BLOB_SIZE="$(du -sh "$OUT/models/blobs" 2>/dev/null | cut -f1)"
if (( BLOB_COUNT < 2 )) || [[ ! -d "$OUT/models/manifests" ]]; then
  echo "Model store looks incomplete: $BLOB_COUNT blobs, manifests $([[ -d "$OUT/models/manifests" ]] && echo present || echo MISSING)" >&2
  exit 1
fi
echo
echo "Model store: $BLOB_COUNT blobs, $BLOB_SIZE"

# ── 4. Record what went in ───────────────────────────────────────────────
cat > "$OUT/MODELS.txt" <<EOF
llm=$LLM_MODEL
embed=$EMBED_MODEL
ollama_client=$CLIENT_VERSION
fetched=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

echo
echo "Models bundled:"
cat "$OUT/MODELS.txt"
du -sh "$OUT"
