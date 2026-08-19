#!/usr/bin/env bash
#
# Verify an Ollama model store, blob by blob.
#
#   ./verify_models.sh [store_dir]        # default /opt/pdas/models
#
# The store is content-addressed: every file in blobs/ is named for the SHA256
# of its own contents. That makes the store self-verifying — no manifest of
# checksums is needed, and none has to survive the transfer. A blob whose
# contents no longer hash to its own name was damaged after it was written,
# which over removable media happens quietly and often enough to be worth
# ruling out first.
#
# Corrupt weights do not announce themselves. Ollama loads them, the model
# answers, and the answer is fluent nonsense — which reads as a bad model or a
# bad prompt and sends people to debug the wrong thing entirely.
#
# Also checks the other direction: that every blob a manifest refers to is
# actually present. A store with manifests and no blobs installs cleanly and
# fails at first use.

set -uo pipefail

STORE="${1:-${OLLAMA_MODELS:-/opt/pdas/models}}"
BLOBS="$STORE/blobs"
MANIFESTS="$STORE/manifests"

CORRUPT=0
MISSING=0
CHECKED=0

echo "Verifying $STORE"
echo "=========="
echo

if [[ ! -d "$BLOBS" ]]; then
  echo "  [FAIL] no blobs directory at $BLOBS" >&2
  echo "         → is that the right store? try: ./verify_models.sh /opt/pdas/models" >&2
  exit 1
fi

# ── 1. Every blob hashes to its own name ─────────────────────────────────
# Hashing several gigabytes is not instant, so report each file as it starts
# rather than leaving the operator watching a still cursor for two minutes.
echo "Blobs"
for path in "$BLOBS"/sha256-*; do
  [[ -e "$path" ]] || { echo "  [WARN] blobs/ is empty"; break; }

  name="$(basename "$path")"
  expected="${name#sha256-}"
  size="$(du -h "$path" | cut -f1)"

  printf '  %-14s %6s  ' "${expected:0:12}…" "$size"

  actual="$(sha256sum "$path" | cut -d' ' -f1)"
  CHECKED=$((CHECKED+1))

  if [[ "$actual" == "$expected" ]]; then
    echo "OK"
  else
    echo "CORRUPT"
    echo "         → expected $expected"
    echo "         → actual   $actual"
    CORRUPT=$((CORRUPT+1))
  fi
done

# ── 2. Every blob a manifest names is present ────────────────────────────
# Parsed with grep rather than jq: the air-gapped server has no package
# manager to install one from, and the digests are unambiguous in the raw
# JSON anyway.
echo
echo "Manifests"
if [[ -d "$MANIFESTS" ]]; then
  while IFS= read -r manifest; do
    tag="${manifest#"$MANIFESTS"/}"
    absent=0

    while IFS= read -r digest; do
      [[ -f "$BLOBS/sha256-${digest#sha256:}" ]] || {
        echo "  [FAIL] $tag references a blob that is not here: $digest"
        absent=$((absent+1))
        MISSING=$((MISSING+1))
      }
    done < <(grep -o 'sha256:[0-9a-f]\{64\}' "$manifest" | sort -u)

    (( absent == 0 )) && echo "  [ OK ] $tag"
  done < <(find "$MANIFESTS" -type f | sort)
else
  echo "  [FAIL] no manifests directory — the store holds weights it cannot name"
  MISSING=$((MISSING+1))
fi

# ── 3. Verdict ───────────────────────────────────────────────────────────
echo
echo "=========="
echo "$CHECKED blobs checked, $CORRUPT corrupt, $MISSING missing"

if (( CORRUPT > 0 )); then
  echo
  echo "The weights are damaged. Re-copy the store from the build machine —"
  echo "a corrupt blob cannot be repaired in place, and Ollama will keep"
  echo "producing plausible-looking nonsense until it is replaced."
  exit 1
fi

if (( MISSING > 0 )); then
  echo
  echo "Blobs are intact but incomplete. Copy blobs/ AND manifests/ together;"
  echo "copying only one leaves a store that installs and then fails."
  exit 1
fi

echo "Store is intact."
