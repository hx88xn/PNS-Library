#!/usr/bin/env bash
#
# Download every Python dependency as a wheel, for installation on a machine
# with no internet.
#
# RUN THIS ON A CONNECTED MACHINE WHOSE UBUNTU RELEASE AND PYTHON MINOR VERSION
# MATCH THE SERVER EXACTLY. Wheel filenames encode both. A wheel built for
# cp312 will not install under cp310, and the error message pip gives is
# "no matching distribution found" — which reads like a network problem and
# sends people hunting in the wrong place for an afternoon.
#
# The simplest way to guarantee a match is to run this inside the same WSL2
# Ubuntu image you will deploy to, while it still has network access.
#
#   ./deploy/fetch_wheels.sh [output_dir]

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/offline/wheels}"

PYTHON="${PYTHON:-python3}"
PY_VERSION="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

echo "Python      $PY_VERSION  ($("$PYTHON" -c 'import sys; print(sys.executable)'))"
echo "Platform    $(uname -s) $(uname -m)"
echo "Output      $OUT"
echo

CROSS_PLATFORM_ARGS=()

if [[ "$(uname -s)" != "Linux" ]]; then
  cat >&2 <<'WARN'
WARNING: you are not on Linux.

Cross-platform `pip download` works, but it is fragile: with --platform, pip
matches wheel tags as LITERAL STRINGS rather than by compatibility. Ask only
for manylinux_2_28 and pip rejects pydantic-core's perfectly installable
manylinux_2_17 wheels, then backtracks through hundreds of versions before
failing with a message that blames pydantic-core rather than the tag.

Every compatible tag is passed below to work around that. It still cannot see
your server's real glibc, so prefer running this inside the WSL2 image you
will deploy to, where pip uses proper compatibility logic.
WARN
  read -rp "Continue anyway? [y/N] " reply
  [[ "$reply" == "y" ]] || exit 1

  CROSS_PLATFORM_ARGS=(
    --platform manylinux_2_17_x86_64
    --platform manylinux2014_x86_64
    --platform manylinux_2_28_x86_64
    --platform manylinux_2_35_x86_64
    --python-version "${TARGET_PY_VERSION:-3.12}"
  )
fi

mkdir -p "$OUT"

# pip itself must be in the bundle: the air-gapped venv is created with
# --without-pip and bootstrapped from these wheels.
"$PYTHON" -m pip download \
  --dest "$OUT" \
  --only-binary=:all: \
  "${CROSS_PLATFORM_ARGS[@]}" \
  pip setuptools wheel

"$PYTHON" -m pip download \
  --dest "$OUT" \
  --only-binary=:all: \
  "${CROSS_PLATFORM_ARGS[@]}" \
  -r "$ROOT/backend/requirements.in"

echo
echo "Wheels: $(find "$OUT" -name '*.whl' | wc -l | tr -d ' ')"
du -sh "$OUT"

# Any sdist here means a package had no wheel for this platform, and it will
# try to compile on the offline box — where there is no compiler and no
# network to fetch build dependencies.
if find "$OUT" -name '*.tar.gz' -o -name '*.zip' | grep -q .; then
  echo
  echo "PROBLEM: source distributions were downloaded:" >&2
  find "$OUT" \( -name '*.tar.gz' -o -name '*.zip' \) -exec basename {} \; >&2
  echo "These will fail to install offline. Pin a version that publishes a wheel." >&2
  exit 1
fi

echo "OK — wheels only, no source distributions."
