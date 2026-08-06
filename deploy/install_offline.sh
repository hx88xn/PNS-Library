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

# `set -e` aborts silently, which on an air-gapped box leaves you with a
# half-installed system and no idea which step failed. Report the line and the
# command instead.
trap 'rc=$?; echo >&2; echo "INSTALL FAILED at line $LINENO (exit $rc):" >&2; echo "  $BASH_COMMAND" >&2; echo >&2; echo "Re-run with: sudo bash -x $0   to see the full trace." >&2; exit $rc' ERR

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

# ── 0b. Vendored system packages ─────────────────────────────────────────
# Optional. Present when fetch_debs.sh was run — typically to supply a Python
# the server's Ubuntu does not ship, since apt cannot reach an archive here.
if compgen -G "$HERE/debs/*.deb" >/dev/null; then
  echo "Installing vendored system packages…"
  # dpkg does not resolve dependencies, so a single pass can fail purely on
  # ordering. Running it twice settles that without needing an archive; only
  # the second failure is real.
  dpkg -i "$HERE"/debs/*.deb >/dev/null 2>&1 || true
  if ! dpkg -i "$HERE"/debs/*.deb; then
    echo "Some packages failed to install. Their dependencies are missing" >&2
    echo "from the bundle — re-run fetch_debs.sh on a machine matching this" >&2
    echo "Ubuntu release." >&2
    exit 1
  fi
  echo "  $(ls -1 "$HERE"/debs/*.deb | wc -l | tr -d ' ') packages installed"
fi

# Prefer a vendored 3.12 over the system default: the wheels are built for one
# specific Python minor version and will not install on another.
if [[ -z "${PYTHON:-}" ]] && command -v python3.12 >/dev/null; then
  PYTHON=/usr/bin/python3.12
  echo "Using $PYTHON (matches the cp312 wheels)"
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
PY_TAG="cp$("$PYTHON" -c 'import sys;print(f"{sys.version_info.major}{sys.version_info.minor}")')"

# Wheel filenames encode the Python minor version. Catching a mismatch here is
# the difference between one clear sentence and a wall of "No matching
# distribution found" that reads like a network fault.
#
# Only VERSION-SPECIFIC wheels are comparable — those tagged cp312-cp312. A
# stable-ABI wheel is tagged cp39-abi3 and runs on 3.9 *and later*, so reading
# its tag as a requirement produces a false mismatch on a perfectly good
# install. Ignore anything with abi3 in the name.
# A version-specific wheel repeats its tag: numpy-2.5.1-cp312-cp312-<platform>.
# Matching that with a backreference would be neater but is not portable —
# POSIX ERE has none, and non-GNU greps reject \1 outright. Pull out every cp
# tag and check the first two are equal instead.
WHEEL_TAG=""
if compgen -G "$PREFIX/wheels/*.whl" >/dev/null; then
  for whl in "$PREFIX"/wheels/*.whl; do
    name="$(basename "$whl")"
    [[ "$name" == *abi3* ]] && continue
    tags="$(grep -oE 'cp[0-9]{2,3}' <<<"$name")"
    [[ "$(wc -l <<<"$tags")" -ge 2 ]] || continue
    if [[ "$(sed -n 1p <<<"$tags")" == "$(sed -n 2p <<<"$tags")" ]]; then
      WHEEL_TAG="$(sed -n 1p <<<"$tags")"
      break
    fi
  done
fi

if [[ -n "$WHEEL_TAG" ]]; then
  if [[ "$WHEEL_TAG" != "$PY_TAG" ]]; then
    cat >&2 <<EOF

PYTHON VERSION MISMATCH

  This machine: $("$PYTHON" --version)  ($PY_TAG)
  The wheels:   $WHEEL_TAG

Compiled wheels will not install. Either:
  - install the matching Python and re-run with
        sudo PYTHON=/usr/bin/python3.XX ./install_offline.sh
  - or rebuild the wheels on a machine running this Python version.
EOF
    exit 1
  fi
fi

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
