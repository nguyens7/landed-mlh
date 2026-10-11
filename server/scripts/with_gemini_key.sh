#!/usr/bin/env bash
# Run a command with GEMINI_API_KEY in its environment only (never printed, never written to disk).
# Usage: server/scripts/with_gemini_key.sh uv run --project server uvicorn landed_server.app:app
# The key comes from your shell, or from Secret Manager via the untracked secrets.local.sh.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
[ -f "$here/secrets.local.sh" ] && . "$here/secrets.local.sh"
fetch() { gcloud secrets versions access latest --secret="$1" --project="$LANDED_GCP_PROJECT"; }
if [ -z "${GEMINI_API_KEY:-}" ]; then
  [ -n "${LANDED_GCP_PROJECT:-}" ] && [ -n "${LANDED_GEMINI_SECRET:-}" ] || { echo "Set GEMINI_API_KEY (see README)." >&2; exit 1; }
  GEMINI_API_KEY="$(fetch "$LANDED_GEMINI_SECRET")"
fi
export GEMINI_API_KEY
exec "$@"
