#!/usr/bin/env bash
#
# Install PDAS on the air-gapped Ubuntu VM. Run from inside the unpacked
# bundle directory:
#
#   sudo ./install_offline.sh
#
# Makes no network calls. If pip reaches for the index, something is wrong with
# the wheel set and the run aborts rather than hanging on a connection that
# will never open.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PDAS_PREFIX:-/opt/pdas}"
SERVICE_USER="${PDAS_USER:-pdas}"

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

# This script lives beside the unpacked bundle, not in the git repo. Running it
# from deploy/ fails several steps in with a bare `cp: cannot stat` — say so up
# front instead.
for REQUIRED in app wheels; do
  [[ -d "$HERE/$REQUIRED" ]] && continue
  cat >&2 <<EOF
Missing $HERE/$REQUIRED

Run this from the directory where the bundle was unpacked, not from the repo:

    cd <bundle-dir>
    tar -xf  pdas-runtime-*.tar
    tar -xzf pdas-app-*.tar.gz
    sudo ./install_offline.sh

That directory should contain app/, wheels/, ollama/ and client/.
EOF
  exit 1
done

echo "Installing to $PREFIX"

# ── 0. Verify the transfer ───────────────────────────────────────────────
# The bundle ships two manifests: RUNTIME_SHA256SUMS (wheels + models) and
# APP_SHA256SUMS (source + scripts). SHA256SUMS is the pre-split single-archive
# name, still accepted so an older bundle installs unchanged.
VERIFIED=0
for MANIFEST in SHA256SUMS RUNTIME_SHA256SUMS APP_SHA256SUMS; do
  [[ -f "$HERE/$MANIFEST" ]] || continue
  echo "Verifying $MANIFEST…"
  ( cd "$HERE" && sha256sum -c --quiet "$MANIFEST" ) || {
    echo "CHECKSUM MISMATCH in $MANIFEST — the transfer is corrupt." >&2
    echo "Re-download the affected file. Do not proceed." >&2
    exit 1
  }
  VERIFIED=1
done

if (( VERIFIED )); then
  echo "  contents intact"
else
  # Silence here would mean a corrupt 5 GB transfer installs happily and fails
  # later in a way that looks like a code bug.
  echo "WARNING: no checksum manifest found — the transfer is UNVERIFIED." >&2
  echo "         Expected RUNTIME_SHA256SUMS and APP_SHA256SUMS beside this script." >&2
  read -rp "Continue without verification? [y/N] " reply
  [[ "$reply" == "y" ]] || exit 1
fi

# ── 1. Service account and layout ────────────────────────────────────────
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"

# var/config and var/cache stand in for the home directory the service unit
# redirects HOME to — see the Environment= lines in pdas.service.
mkdir -p "$PREFIX"/{app,var,wheels} "$PREFIX"/var/{config,cache}
cp -r "$HERE/app/." "$PREFIX/app/"
cp -r "$HERE/wheels/." "$PREFIX/wheels/"

# ── 2. Python environment, wheels only ───────────────────────────────────
PYTHON="${PYTHON:-python3}"
echo "Creating virtualenv with $("$PYTHON" --version)"

"$PYTHON" -m venv --without-pip "$PREFIX/venv"

# --no-index is the load-bearing flag: it turns "reached for the network" from
# a silent 15-minute timeout into an immediate, legible failure.
PIP_ARGS=(--no-index --find-links "$PREFIX/wheels" --disable-pip-version-check)

"$PREFIX/venv/bin/python" - <<'PY'
import glob, os, runpy, sys
prefix = os.environ.get("PDAS_PREFIX", "/opt/pdas")
wheels = glob.glob(os.path.join(prefix, "wheels", "pip-*.whl"))
if not wheels:
    sys.exit("No pip wheel in the bundle — rerun fetch_wheels.sh")
sys.path.insert(0, wheels[0])
sys.argv = ["pip", "install", "--no-index", "--find-links",
            os.path.join(prefix, "wheels"), wheels[0]]
runpy.run_module("pip", run_name="__main__")
PY

"$PREFIX/venv/bin/pip" install "${PIP_ARGS[@]}" -r "$PREFIX/app/requirements.in"
"$PREFIX/venv/bin/pip" install "${PIP_ARGS[@]}" -e "$PREFIX/app"

# ── 3. Ollama runtime and models ─────────────────────────────────────────
RUNTIME="$HERE/ollama/ollama-linux-amd64.tar.zst"
if [[ -f "$RUNTIME" ]]; then
  echo "Installing Ollama runtime"
  # zstd, not gzip. GNU tar 1.31+ handles --zstd directly (Ubuntu 22.04 and
  # later); fall back to piping through unzstd on anything older.
  if tar --zstd -tf "$RUNTIME" >/dev/null 2>&1; then
    tar --zstd -xf "$RUNTIME" -C /usr/local
  elif command -v unzstd >/dev/null; then
    unzstd -c "$RUNTIME" | tar -xf - -C /usr/local
  else
    echo "Cannot extract $RUNTIME — install zstd, or unpack it on the build machine." >&2
    exit 1
  fi
fi

if [[ -d "$HERE/ollama/models" ]]; then
  echo "Installing model store"
  install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$PREFIX/models"
  cp -r "$HERE/ollama/models/." "$PREFIX/models/"
fi

# ── 4. Configuration ─────────────────────────────────────────────────────
if [[ ! -f "$PREFIX/pdas.env" ]]; then
  SECRET="$(head -c 32 /dev/urandom | base64 | tr -d '=+/' | cut -c1-40)"
  cat > "$PREFIX/pdas.env" <<EOF
PDAS_DATA_DIR=$PREFIX/var
PDAS_OLLAMA_HOST=http://127.0.0.1:11434
PDAS_LLM_MODEL=$(sed -n 's/^llm=//p' "$HERE/ollama/MODELS.txt" 2>/dev/null || echo qwen3.5:4b)
PDAS_EMBED_MODEL=$(sed -n 's/^embed=//p' "$HERE/ollama/MODELS.txt" 2>/dev/null || echo bge-m3)
PDAS_JWT_SECRET=$SECRET
PDAS_HOST=0.0.0.0
PDAS_PORT=8000
EOF
  chmod 600 "$PREFIX/pdas.env"
  echo "Wrote $PREFIX/pdas.env with a generated JWT secret"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX"

# ── 4b. CLI wrapper ──────────────────────────────────────────────────────
# systemd reads pdas.env through EnvironmentFile; a shell does not. Without
# this the CLI falls back to the relative default data dir and tries to create
# ./var in whatever directory you happen to be standing in — which fails as
# the service account and looks like a permissions bug rather than a config
# one. The wrapper makes `pdas` behave identically either way.
cat > /usr/local/bin/pdas <<'WRAPPER'
#!/bin/sh
# PDAS CLI — loads the deployment config, then runs the real entry point.
set -a
[ -r /opt/pdas/pdas.env ] && . /opt/pdas/pdas.env
set +a
exec /opt/pdas/venv/bin/pdas "$@"
WRAPPER
chmod 755 /usr/local/bin/pdas

# ── 5. Services ──────────────────────────────────────────────────────────
install -m 644 "$HERE/ollama.service" /etc/systemd/system/ollama.service
install -m 644 "$HERE/pdas.service" /etc/systemd/system/pdas.service
systemctl daemon-reload
systemctl enable --now ollama.service
sleep 5
systemctl enable --now pdas.service

cat <<EOF

Installed.

  Service      systemctl status pdas
  Logs         journalctl -u pdas -f
  Config       $PREFIX/pdas.env
  Health       curl -s http://127.0.0.1:8000/api/health

Next:
  1. Create an account:
       sudo -u $SERVICE_USER pdas adduser PN-00000 --role admin
  2. Ingest documents:
       sudo -u $SERVICE_USER pdas ingest /path/to/documents

     Use plain 'pdas' (the wrapper at /usr/local/bin/pdas), not the venv path
     directly — it loads $PREFIX/pdas.env so the CLI and the service read the
     same data directory.
  3. Confirm the GPU is in use:
       nvidia-smi          # the ollama process should appear
  4. Make the service reachable from client PCs — see README-DEPLOY.md,
     "Making WSL2 reachable from the LAN". Without that step only this VM
     can connect, no matter what PDAS_HOST says.
EOF
