#!/usr/bin/env bash
#
# Check whether this machine can host PDAS, BEFORE carrying 5 GB onto it.
#
# Run on the target VM:
#   ./preflight.sh
#
# Reports rather than fixes. Every failure here is far cheaper to find now than
# after the transfer.

set -uo pipefail

PASS=0
FAIL=0
WARN=0

ok()   { echo "  [ OK ] $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $1"; echo "         → $2"; FAIL=$((FAIL+1)); }
warn() { echo "  [WARN] $1"; echo "         → $2"; WARN=$((WARN+1)); }

echo "PDAS preflight  (role: ${PDAS_ROLE:-server})"
echo "=============="
echo

# ── Platform ─────────────────────────────────────────────────────────────
echo "Platform"
if grep -qi microsoft /proc/version 2>/dev/null; then
  ok "running under WSL2"
elif [[ "$(uname -s)" == "Linux" ]]; then
  ok "running on Linux ($(uname -m))"
else
  bad "not Linux" "the bundle targets Ubuntu x86_64"
fi

ARCH="$(uname -m)"
[[ "$ARCH" == "x86_64" ]] && ok "architecture x86_64" \
  || bad "architecture is $ARCH" "the wheel bundle and Ollama build are x86_64"

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  echo "  [INFO] ${PRETTY_NAME:-unknown}"
  echo "         Build the wheel bundle on THIS Ubuntu version."
fi

# ── Python ───────────────────────────────────────────────────────────────
echo
echo "Python"
if command -v python3 >/dev/null; then
  PY="$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  ok "python3 present ($PY)"
  echo "         Wheels must be built for cp${PY/./}. A mismatch fails at install."
  python3 -c 'import venv' 2>/dev/null && ok "venv module available" \
    || bad "venv module missing" "apt-get install python3-venv"
else
  bad "python3 not found" "apt-get install python3 python3-venv"
fi

# ── Extraction tools ─────────────────────────────────────────────────────
echo
echo "Archive tools"
if tar --zstd --help >/dev/null 2>&1; then
  ok "tar supports --zstd (needed for the Ollama runtime)"
elif command -v unzstd >/dev/null; then
  ok "unzstd present (fallback path)"
else
  bad "no zstd support" "apt-get install zstd — the Ollama runtime is a .tar.zst"
fi

# ── GPU ──────────────────────────────────────────────────────────────────
echo
echo "GPU"
if [[ "${PDAS_ROLE:-server}" == "build" ]]; then
  # A build machine downloads models, it never runs them. Absence of a GPU
  # here says nothing about the deployment.
  echo "  [SKIP] build machine — GPU not required for producing the bundle"
elif command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
  GPU="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)"
  ok "nvidia-smi works: $GPU"

  VRAM_MB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)"
  if [[ -n "$VRAM_MB" && "$VRAM_MB" -lt 6000 ]]; then
    warn "only ${VRAM_MB} MB of VRAM" "qwen3.5:4b + bge-m3 need ~4.4 GB resident"
  fi
elif [[ "${PDAS_ALLOW_CPU:-0}" == "1" ]]; then
  warn "no GPU — running on CPU" \
       "Acknowledged via PDAS_ALLOW_CPU=1. Everything works, but generation drops to ~3-8 tok/s. Fine for rehearsing the install; not viable for daily use."
else
  bad "nvidia-smi not working" \
      "Under WSL2 install a current NVIDIA driver on WINDOWS, not inside the VM. Without it Ollama runs on CPU at ~3-8 tok/s. To proceed anyway on a test machine: PDAS_ALLOW_CPU=1 ./preflight.sh"
fi

# ── Memory ───────────────────────────────────────────────────────────────
echo
echo "Memory"
MEM_GB=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1048576 ))
if (( MEM_GB >= 12 )); then
  ok "${MEM_GB} GB RAM"
elif (( MEM_GB >= 8 )); then
  warn "${MEM_GB} GB RAM" "workable; set memory=12GB in %UserProfile%\\.wslconfig if ingestion struggles"
else
  bad "${MEM_GB} GB RAM" "raise it in %UserProfile%\\.wslconfig: [wsl2] memory=12GB"
fi

# ── Disk ─────────────────────────────────────────────────────────────────
echo
echo "Disk"
AVAIL_GB=$(( $(df -Pk /opt 2>/dev/null | tail -1 | awk '{print $4}') / 1048576 ))
if (( AVAIL_GB >= 25 )); then
  ok "${AVAIL_GB} GB free on /"
elif (( AVAIL_GB >= 15 )); then
  warn "${AVAIL_GB} GB free" "tight: models 4.2 GB + runtime ~3 GB extracted + venv + the bundle itself"
else
  bad "${AVAIL_GB} GB free" "need ~25 GB. Note WSL2's virtual disk grows but does not shrink on its own."
fi

# ── Filesystem placement ─────────────────────────────────────────────────
echo
echo "Filesystem"
if [[ "$(pwd)" == /mnt/* ]]; then
  warn "you are on $(pwd)" \
       "Do NOT install under /mnt/c. Model files are memory-mapped and mmap over the 9p bridge is drastically slower. Use /opt/pdas."
else
  ok "not running from a Windows mount"
fi

# ── systemd ──────────────────────────────────────────────────────────────
echo
echo "Service manager"
if pidof systemd >/dev/null 2>&1 || [[ -d /run/systemd/system ]]; then
  ok "systemd is running"
else
  bad "systemd not running" \
      "Add to /etc/wsl.conf:  [boot]\\n systemd=true   then 'wsl --shutdown' from Windows."
fi

# ── Network isolation ────────────────────────────────────────────────────
echo
echo "Network"
if curl -sf --max-time 5 https://pypi.org >/dev/null 2>&1; then
  warn "this machine has internet" "fine for BUILDING the bundle; the target server should not"
else
  ok "no internet (as expected for the target server)"
fi

# ── Verdict ──────────────────────────────────────────────────────────────
echo
echo "=============="
echo "  pass $PASS   warn $WARN   fail $FAIL"
if (( FAIL > 0 )); then
  echo
  echo "Fix the failures above before transferring the bundle."
  exit 1
fi
echo
echo "Ready. Transfer the bundle and run install_offline.sh."
