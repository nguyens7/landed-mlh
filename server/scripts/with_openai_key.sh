#!/usr/bin/env bash
# Run a command with OPENAI_API_KEY, TYPESAFE_API_KEY and GEMINI_API_KEY in its environment only
# (never printed, never written to disk). Keys come from your shell, or from Secret Manager via the
# untracked secrets.local.sh. OpenAI and TypeSafe keys are optional: without them the router falls
# back to Gemini or is off.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
[ -f "$here/secrets.local.sh" ] && . "$here/secrets.local.sh"
fetch() { gcloud secrets versions access latest --secret="$1" --project="$LANDED_GCP_PROJECT"; }
load() {  # load VAR SECRET_NAME_VAR
  local var="$1" name_var="$2"
  if [ -z "${!var:-}" ] && [ -n "${LANDED_GCP_PROJECT:-}" ] && [ -n "${!name_var:-}" ]; then
    printf -v "$var" '%s' "$(fetch "${!name_var}")"
  fi
  [ -n "${!var:-}" ] && export "${var?}"
  return 0
}
load OPENAI_API_KEY LANDED_OPENAI_SECRET
load TYPESAFE_API_KEY LANDED_TYPESAFE_SECRET
load GEMINI_API_KEY LANDED_GEMINI_SECRET
[ -n "${GEMINI_API_KEY:-}" ] || { echo "Set GEMINI_API_KEY (see README)." >&2; exit 1; }
exec "$@"
