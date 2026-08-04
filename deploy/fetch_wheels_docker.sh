#!/usr/bin/env bash
#
# Build the Linux wheel bundle from a non-Linux machine, using Docker.
#
# This is the practical route when you develop on macOS or Windows but deploy
# to Ubuntu. The wheels are downloaded *inside* the same Ubuntu image as the
# server, so pip uses real platform compatibility logic rather than the literal
# tag matching that `pip download --platform` falls back to — which is what
# makes cross-platform downloads fail on packages like pydantic-core.
#
#   ./deploy/fetch_wheels_docker.sh [ubuntu_tag] [output_dir]
#
# The Ubuntu tag MUST match your server. Check with `lsb_release -a` on the VM.
#   24.04 -> Python 3.12
#   22.04 -> Python 3.10

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UBUNTU="${1:-24.04}"
OUT="${2:-$ROOT/offline/wheels}"

command -v docker >/dev/null || { echo "Docker is not installed." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is installed but not running. Start Docker Desktop." >&2; exit 1; }

mkdir -p "$OUT"

echo "Building wheels inside ubuntu:$UBUNTU"
echo "Output: $OUT"
echo

# --platform linux/amd64 matters on Apple Silicon: without it Docker builds
# arm64 wheels, which will not install on an x86_64 server and whose filenames
# look plausible enough that the mistake survives until install day.
docker run --rm \
  --platform linux/amd64 \
  -v "$ROOT/backend/requirements.in:/req.in:ro" \
  -v "$OUT:/wheels" \
  "ubuntu:$UBUNTU" \
  bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3 python3-pip python3-venv >/dev/null

    echo "Python: $(python3 --version)"

    python3 -m venv /tmp/venv
    /tmp/venv/bin/pip install -q --upgrade pip

    # pip itself goes in the bundle: the offline venv is created --without-pip
    # and bootstrapped from these wheels.
    /tmp/venv/bin/pip download --dest /wheels --only-binary=:all: pip setuptools wheel
    /tmp/venv/bin/pip download --dest /wheels --only-binary=:all: -r /req.in
  '

echo
echo "Wheels: $(find "$OUT" -name '*.whl' | wc -l | tr -d ' ')"
du -sh "$OUT"

# An sdist here means a package published no wheel for this platform, and it
# would try to compile on the offline box, where there is no compiler.
if find "$OUT" \( -name '*.tar.gz' -o -name '*.zip' \) | grep -q .; then
  echo
  echo "PROBLEM: source distributions were downloaded:" >&2
  find "$OUT" \( -name '*.tar.gz' -o -name '*.zip' \) -exec basename {} \; >&2
  exit 1
fi

echo "OK — wheels only, built for linux/amd64 on ubuntu:$UBUNTU."
