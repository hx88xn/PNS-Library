#!/usr/bin/env bash
#
# Fetch the Ollama runtime and the two models, ready to carry onto the
# air-gapped server.
#
# RUN THIS ON A CONNECTED LINUX MACHINE (WSL2 is ideal — same platform as the
# target). Pull with the same Ollama version you intend to ship: the on-disk
# manifest format is stable in practice, but matching versions removes one
# variable from a transfer you cannot easily retry.
#
#   ./deploy/fetch_models.sh [output_dir]

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

# ── 2. The models ────────────────────────────────────────────────────────
if ! command -v ollama >/dev/null; then
  echo "ollama is not on PATH. Install it here first, or extract $TARBALL." >&2
  exit 1
fi

if ! ollama list >/dev/null 2>&1; then
  echo "Starting a local ollama server to pull into…"
  ollama serve >/tmp/ollama-fetch.log 2>&1 &
  sleep 4
fi

for model in "$EMBED_MODEL" "$LLM_MODEL"; do
  echo
  echo "Pulling $model"
  ollama pull "$model"
done

# ── 3. Copy the store ────────────────────────────────────────────────────
# ~/.ollama/models is content-addressed: blobs/ holds the weights and
# manifests/ maps tags to them. BOTH are required — copying only blobs leaves
# a server that has the data and no idea what it is called.
SRC="${OLLAMA_MODELS:-$HOME/.ollama/models}"
echo
echo "Copying model store from $SRC"
rm -rf "$OUT/models"
mkdir -p "$OUT/models"
cp -r "$SRC/blobs" "$SRC/manifests" "$OUT/models/"

# ── 4. Record what went in ───────────────────────────────────────────────
cat > "$OUT/MODELS.txt" <<EOF
llm=$LLM_MODEL
embed=$EMBED_MODEL
ollama_client=$(ollama --version 2>/dev/null | head -1)
fetched=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

echo
echo "Models bundled:"
cat "$OUT/MODELS.txt"
du -sh "$OUT"
