#!/usr/bin/env bash
# Trust the local dev TLS certificate for SSL (login keychain). web_slicer_core helper.
# Aligns with scripts/dev-setup-tls.sh: resolve paths first, idempotent trust, stderr diagnostics.
# Does not create or modify PEM files under tls/.
# Comments and user-facing messages are in English per project convention.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

log_skip() { echo "==> $* (skip — already satisfied)"; }
log_do() { echo "==> $*"; }

resolve_cert_path() {
  local p
  p="${AGENT_TLS_CERTFILE:-}"
  if [[ -n "$p" ]]; then
    if [[ -f "$p" ]]; then
      printf '%s' "$p"
      return 0
    fi
    echo "WARNING: AGENT_TLS_CERTFILE is set but file not found: $p (trying other locations)" >&2
  fi
  p="${BUNDLE_TLS_CERT_PATH:-}"
  if [[ -n "$p" ]]; then
    if [[ -f "$p" ]]; then
      printf '%s' "$p"
      return 0
    fi
    echo "WARNING: BUNDLE_TLS_CERT_PATH is set but file not found: $p (trying other locations)" >&2
  fi
  p="${SSL_CERTFILE:-}"
  if [[ -n "$p" ]]; then
    if [[ -f "$p" ]]; then
      printf '%s' "$p"
      return 0
    fi
    echo "WARNING: SSL_CERTFILE is set but file not found: $p (trying other locations)" >&2
  fi
  for c in \
    "$REPO_ROOT/agent/tls/localhost.crt" \
    "$REPO_ROOT/tls/localhost.crt" \
    "$REPO_ROOT/../Bundle-Launcher/bundle-mac/agent/tls/localhost.crt" \
    "$REPO_ROOT/../Bundle-Launcher/bundle-win/agent/tls/localhost.crt"; do
    [[ -f "$c" ]] && { printf '%s' "$c"; return 0; }
  done
  return 1
}

ensure_macos_trust() {
  local cert="$1"
  local KEYCHAIN="${HOME}/Library/Keychains/login.keychain-db"
  if [[ ! -f "$KEYCHAIN" ]]; then
    KEYCHAIN="${HOME}/Library/Keychains/login.keychain"
  fi

  log_do "Trust certificate for SSL (login keychain; GUI may prompt)"
  echo "    $cert"

  local logf rc
  logf="$(mktemp)"
  set +e
  security add-trusted-cert -r trustRoot -p ssl -k "$KEYCHAIN" "$cert" 2>"$logf"
  rc=$?
  set -e

  if [[ "$rc" -eq 0 ]]; then
    echo "Trusted certificate added."
    rm -f "$logf"
    return 0
  fi

  if grep -Eiq 'already exists|duplicate|SecDuplicateItem|exists in the keychain' "$logf" 2>/dev/null; then
    log_skip "macOS trust (certificate already in keychain)"
    rm -f "$logf"
    return 0
  fi

  cat "$logf" >&2 || true
  rm -f "$logf"
  echo "security add-trusted-cert failed. Import manually: Keychain Access -> File -> Import Items -> Trust SSL."
  exit "$rc"
}

# --- main ---

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only."
  exit 1
fi

CERT="$(resolve_cert_path)" || true
if [[ -z "${CERT:-}" ]] || [[ ! -f "$CERT" ]]; then
  echo "TLS certificate not found."
  echo "  Place PEM at: $REPO_ROOT/agent/tls/localhost.crt (or $REPO_ROOT/tls/localhost.crt)"
  echo "  Or set AGENT_TLS_CERTFILE, BUNDLE_TLS_CERT_PATH, or SSL_CERTFILE to an existing .crt/.pem."
  exit 1
fi

ensure_macos_trust "$CERT"

echo ""
echo "Restart the browser, then try https://127.0.0.1:5179 and https://127.0.0.1:5180"
echo "Optional for Node:"
echo "  export NODE_EXTRA_CA_CERTS=\"$CERT\""
