#!/usr/bin/env bash
#
# Assemble the transfer artifacts.
#
#   ./deploy/make_bundle.sh                 two archives: runtime + app
#   ./deploy/make_bundle.sh --app-only      just the app archive (~1 MB)
#   ./deploy/make_bundle.sh --split 1G      also split the runtime into parts
#
# Deliberately TWO archives, not one:
#
#   pdas-runtime-*.tar   ~5 GB   wheels, Ollama runtime, model blobs
#                                Transfer once. Changes only when you change
#                                model or dependency versions.
#   pdas-app-*.tar.gz    ~1 MB   backend source, install script, service units
#                                Transfer on every code change.
#
# Over a slow link that difference is the whole game: after the first transfer,
# shipping a fix costs a megabyte instead of five gigabytes.
#
# The runtime archive is UNCOMPRESSED on purpose. Model blobs are quantised
# weights and the Ollama runtime is already zstd — gzipping them burns minutes
# of CPU for a percent or two, and on a machine you are waiting on that is a
# bad trade.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="$ROOT/offline"
STAMP="$(date -u +%Y%m%d)"

APP_ARCHIVE="$ROOT/pdas-app-$STAMP.tar.gz"
RUNTIME_ARCHIVE="$ROOT/pdas-runtime-$STAMP.tar"

APP_ONLY=0
SPLIT_SIZE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-only) APP_ONLY=1; shift ;;
    --split)    SPLIT_SIZE="${2:?--split needs a size, e.g. 1G}"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if (( ! APP_ONLY )); then
  [[ -d "$STAGE/wheels" ]] || {
    cat >&2 <<'EOF'
Missing offline/wheels.

Either run ./deploy/fetch_wheels.sh on a Linux machine matching the server, or
download the pdas-wheels-* artifact from the "Build offline bundle" GitHub
Actions run and unzip it to offline/wheels/.
EOF
    exit 1
  }

  if [[ ! -d "$STAGE/ollama/models" ]]; then
    if [[ "${ALLOW_NO_MODELS:-0}" == "1" ]]; then
      echo "WARNING: no models in the runtime archive. The server will need"
      echo "         offline/ollama/ supplied separately."
      mkdir -p "$STAGE/ollama"
    else
      echo "Missing $STAGE/ollama/models — run fetch_models.sh," >&2
      echo "or set ALLOW_NO_MODELS=1 to build without them." >&2
      exit 1
    fi
  fi
fi

# ── Backend source ───────────────────────────────────────────────────────
rm -rf "$STAGE/app"
mkdir -p "$STAGE/app"
cp -r "$ROOT/backend/pdas" "$STAGE/app/"
cp -r "$ROOT/backend/evals" "$STAGE/app/"
cp "$ROOT/backend/requirements.in" "$ROOT/backend/pyproject.toml" "$STAGE/app/"
find "$STAGE/app" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# ── Install machinery ────────────────────────────────────────────────────
# preflight.sh ships too: the runbook says to run it on the target before
# installing, and the target has no way to fetch it. verify_models.sh likewise
# — corrupt weights answer fluently in nonsense, and the operator needs to be
# able to rule that out on the box rather than infer it from bad answers.
cp "$ROOT/deploy/install_offline.sh" "$ROOT/deploy/preflight.sh" \
   "$ROOT/deploy/verify_models.sh" "$STAGE/"
cp "$ROOT/deploy/pdas.service" "$ROOT/deploy/ollama.service" "$STAGE/"
for doc in README-DEPLOY.md RUNBOOK.md; do
  cp "$ROOT/$doc" "$STAGE/" 2>/dev/null || true
done
chmod +x "$STAGE/install_offline.sh" "$STAGE/preflight.sh" "$STAGE/verify_models.sh"

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

# ── App archive: small, transferred often ────────────────────────────────
# Checksums for just the app files, so this archive verifies on its own.
( cd "$STAGE" && find app client install_offline.sh preflight.sh verify_models.sh *.service *.md -type f 2>/dev/null \
    | sort | xargs sha256sum > APP_SHA256SUMS )

DOCS=()
for doc in README-DEPLOY.md RUNBOOK.md; do
  [[ -f "$STAGE/$doc" ]] && DOCS+=("$doc")
done

echo "Creating $(basename "$APP_ARCHIVE")"
tar -czf "$APP_ARCHIVE" -C "$STAGE" \
  app client install_offline.sh preflight.sh verify_models.sh \
  pdas.service ollama.service \
  APP_SHA256SUMS "${DOCS[@]}"

echo "  $(du -h "$APP_ARCHIVE" | cut -f1)"

# ── Runtime archive: large, transferred once ─────────────────────────────
if (( ! APP_ONLY )); then
  echo
  # debs/ is optional — present only when fetch_debs.sh was run.
  RUNTIME_DIRS=(wheels ollama)
  [[ -d "$STAGE/debs" ]] && RUNTIME_DIRS+=(debs)

  echo "Computing runtime checksums (this walks ~5 GB)…"
  ( cd "$STAGE" && find "${RUNTIME_DIRS[@]}" -type f 2>/dev/null \
      | sort | xargs sha256sum > RUNTIME_SHA256SUMS )

  echo "Creating $(basename "$RUNTIME_ARCHIVE") — uncompressed, models do not compress"
  tar -cf "$RUNTIME_ARCHIVE" -C "$STAGE" "${RUNTIME_DIRS[@]}" RUNTIME_SHA256SUMS

  echo "  $(du -h "$RUNTIME_ARCHIVE" | cut -f1)"

  # Splitting turns a failed 5 GB upload into a failed 1 GB part. Worth it on
  # any link you do not trust, and Drive handles the parts individually.
  if [[ -n "$SPLIT_SIZE" ]]; then
    echo
    echo "Splitting into $SPLIT_SIZE parts…"
    # Plain -b with a prefix only: --additional-suffix and -d are GNU-only, and
    # the default aa/ab/ac suffixes sort correctly for `cat` on every platform.
    split -b "$SPLIT_SIZE" "$RUNTIME_ARCHIVE" "$RUNTIME_ARCHIVE.part."

    # Record BASENAMES, not full paths. sha256sum writes whatever path it was
    # given, so absolute paths from this build machine would be meaningless on
    # the target — verification fails there with "could not be read", which
    # looks like a corrupt transfer rather than a bad manifest.
    ARCHIVE_NAME="$(basename "$RUNTIME_ARCHIVE")"
    ( cd "$ROOT" && sha256sum "$ARCHIVE_NAME".part.* > "$ARCHIVE_NAME.parts.sha256" )
    rm -f "$RUNTIME_ARCHIVE"
    echo "  $(ls "$RUNTIME_ARCHIVE".part.* | wc -l | tr -d ' ') parts"
    ls -lh "$RUNTIME_ARCHIVE".part.* | awk '{print "    "$9"  "$5}'
  fi
fi

# ── What to do next ──────────────────────────────────────────────────────
cat <<EOF

────────────────────────────────────────────────────────────────────
FIRST INSTALL — transfer both, unpack into the same directory:

  tar -xf  pdas-runtime-$STAMP.tar
  tar -xzf pdas-app-$STAMP.tar.gz
  sha256sum -c RUNTIME_SHA256SUMS
  sha256sum -c APP_SHA256SUMS
  sudo ./install_offline.sh

LATER UPDATES — app archive only (~$(du -h "$APP_ARCHIVE" | cut -f1)):

  ./deploy/make_bundle.sh --app-only
  # on the server, in the same directory as before:
  tar -xzf pdas-app-<date>.tar.gz
  sudo ./install_offline.sh
EOF

if [[ -n "$SPLIT_SIZE" ]]; then
  cat <<EOF

REASSEMBLE the split runtime before unpacking:

  sha256sum -c pdas-runtime-$STAMP.tar.parts.sha256
  cat pdas-runtime-$STAMP.tar.part.* > pdas-runtime-$STAMP.tar
EOF
fi
echo "────────────────────────────────────────────────────────────────────"
