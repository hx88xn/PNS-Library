#!/usr/bin/env bash
#
# Assemble everything into one archive to carry through the transfer channel.
#
#   ./deploy/make_bundle.sh
#
# Expects fetch_wheels.sh and fetch_models.sh to have run already. The Electron
# installer is optional here — build it on any connected machine with
# `npm run dist -- --win` and drop the .exe into offline/client/ before running
# this, or transfer it separately.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="$ROOT/offline"
STAMP="$(date -u +%Y%m%d)"
ARCHIVE="$ROOT/pdas-offline-$STAMP.tar.gz"

[[ -d "$STAGE/wheels" ]] || { echo "Missing $STAGE/wheels — run fetch_wheels.sh" >&2; exit 1; }
[[ -d "$STAGE/ollama/models" ]] || { echo "Missing $STAGE/ollama/models — run fetch_models.sh" >&2; exit 1; }

# ── Backend source ───────────────────────────────────────────────────────
rm -rf "$STAGE/app"
mkdir -p "$STAGE/app"
cp -r "$ROOT/backend/pdas" "$STAGE/app/"
cp -r "$ROOT/backend/evals" "$STAGE/app/"
cp "$ROOT/backend/requirements.in" "$ROOT/backend/pyproject.toml" "$STAGE/app/"
find "$STAGE/app" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# ── Install machinery ────────────────────────────────────────────────────
cp "$ROOT/deploy/install_offline.sh" "$STAGE/"
cp "$ROOT/deploy/pdas.service" "$ROOT/deploy/ollama.service" "$STAGE/"
cp "$ROOT/README-DEPLOY.md" "$STAGE/" 2>/dev/null || true
chmod +x "$STAGE/install_offline.sh"

mkdir -p "$STAGE/client"
if ! find "$STAGE/client" -name '*.exe' | grep -q .; then
  cat > "$STAGE/client/README.txt" <<'EOF'
The Electron installer for client PCs goes here.

Build it on a connected machine (electron-builder downloads Electron and NSIS
at build time, so building offline means pre-seeding caches for no benefit):

    npm install
    npm run dist -- --win

Copy dist/PDAS-Setup-*.exe into this directory before making the bundle, or
transfer it separately.
EOF
fi

# ── Checksums ────────────────────────────────────────────────────────────
# Multi-gigabyte transfers over removable media do corrupt files, silently and
# occasionally. Verifying on arrival is not optional.
echo "Computing checksums…"
( cd "$STAGE" && find . -type f ! -name SHA256SUMS -exec sha256sum {} + > SHA256SUMS )

# ── Archive ──────────────────────────────────────────────────────────────
echo "Creating $ARCHIVE"
tar -czf "$ARCHIVE" -C "$ROOT" offline

echo
echo "Bundle:   $ARCHIVE"
echo "Size:     $(du -h "$ARCHIVE" | cut -f1)"
echo "Contents:"
du -sh "$STAGE"/* | sed 's/^/  /'
echo
echo "Verify after transfer with:"
echo "  tar -xzf $(basename "$ARCHIVE") && cd offline && sha256sum -c SHA256SUMS"
