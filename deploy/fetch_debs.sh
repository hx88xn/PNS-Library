#!/usr/bin/env bash
#
# Vendor Ubuntu packages (.deb) so the offline server can install system
# software with no archive access.
#
# RUN ON A CONNECTED MACHINE WHOSE UBUNTU RELEASE MATCHES THE SERVER. Debian
# packages are release-specific: a noble .deb will not satisfy dependencies on
# jammy, and dpkg fails at install time rather than at download time.
#
#   ./deploy/fetch_debs.sh [group...]
#
# Groups:
#   core      python3.12, venv, zstd            always included
#   gui       Electron/X11 runtime libraries    only if a GUI runs on the server
#   node      nodejs + npm                      only if you build the client there
#
# Default is core. The frontend normally runs on client PCs as a prebuilt .exe,
# so gui and node are usually unnecessary — see README-DEPLOY.md.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/offline/debs"

CORE_PKGS=(python3.12 python3.12-venv python3.12-dev zstd)

# Electron needs these shared objects; without them the binary dies with
# "libnss3.so: cannot open shared object file". Names carry the t64 suffix on
# Ubuntu 24.04 (the 64-bit time_t transition) and not on older releases, so
# both spellings are tried and whichever resolves is taken.
GUI_PKGS=(
  libnss3 libgbm1 libxss1 libxtst6 libsecret-1-0 xdg-utils
  libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libgtk-3-0t64 libasound2t64
  libatk1.0-0   libatk-bridge2.0-0   libcups2   libgtk-3-0   libasound2
)

NODE_PKGS=(nodejs npm)

GROUPS=("${@:-core}")
PKGS=()
for group in "${GROUPS[@]}"; do
  case "$group" in
    core) PKGS+=("${CORE_PKGS[@]}") ;;
    gui)  PKGS+=("${GUI_PKGS[@]}") ;;
    node) PKGS+=("${NODE_PKGS[@]}") ;;
    *)    echo "Unknown group: $group (core|gui|node)" >&2; exit 1 ;;
  esac
done

[[ "$(uname -s)" == "Linux" ]] || { echo "Run this on the target Ubuntu release." >&2; exit 1; }

. /etc/os-release
echo "Building .deb set for ${PRETTY_NAME}"
echo "Groups: ${GROUPS[*]}"
echo

mkdir -p "$OUT"
cd "$OUT"

sudo apt-get update -qq

# Resolve each package with its full dependency closure. --print-uris lists
# what apt would fetch; --reinstall forces packages already present on this
# build machine to be listed too, which they otherwise would not be.
RESOLVED=()
for pkg in "${PKGS[@]}"; do
  if apt-cache show "$pkg" >/dev/null 2>&1; then
    RESOLVED+=("$pkg")
  else
    echo "  skip $pkg (not in this release's archive)"
  fi
done

[[ ${#RESOLVED[@]} -gt 0 ]] || { echo "Nothing to download." >&2; exit 1; }

echo
echo "Downloading ${#RESOLVED[@]} packages and their dependencies…"
apt-get install --reinstall --print-uris -qq -y "${RESOLVED[@]}" \
  | cut -d"'" -f2 | grep -E '^https?://' | sort -u > /tmp/deb-uris.txt

wc -l < /tmp/deb-uris.txt | xargs echo "  URIs:"
wget -q --show-progress -N -i /tmp/deb-uris.txt

echo
echo "Packages: $(ls -1 *.deb 2>/dev/null | wc -l | tr -d ' ')"
du -sh "$OUT"
sha256sum *.deb > SHA256SUMS.debs

cat <<EOF

Installed on the server by install_offline.sh, before the venv is built:

    dpkg -i offline/debs/*.deb

dpkg does not resolve dependencies, so order matters — the installer runs it
twice, which settles any ordering problems without an archive.
EOF
