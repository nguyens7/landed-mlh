"""Load provider keys into this process only (never printed or written).

Keys come from the environment (GEMINI_API_KEY, OPENAI_API_KEY). Optionally, they can be fetched
from GCP Secret Manager when LANDED_GCP_PROJECT and the matching secret-name variable
(LANDED_GEMINI_SECRET, LANDED_OPENAI_SECRET) are set, e.g. by sourcing the untracked
server/scripts/secrets.local.sh. No project or secret names are kept in the repository.
"""

import os
import subprocess

SECRET_NAME_VARS = {"OPENAI_API_KEY": "LANDED_OPENAI_SECRET", "GEMINI_API_KEY": "LANDED_GEMINI_SECRET"}


def _load(env: str) -> None:
    if os.environ.get(env):
        return
    project = os.environ.get("LANDED_GCP_PROJECT")
    secret = os.environ.get(SECRET_NAME_VARS[env])
    if not (project and secret):
        raise SystemExit(f"{env} is not set. Export it in your shell (see README).")
    res = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest", f"--secret={secret}", f"--project={project}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise SystemExit(f"Secret Manager access failed for {env}; stopping (no fallback credentials).")
    os.environ[env] = res.stdout.strip()


def ensure_openai_key() -> None:
    _load("OPENAI_API_KEY")


def ensure_gemini_key() -> None:
    _load("GEMINI_API_KEY")


def gemini_client(timeout_s: float = 40.0):
    """Gemini client with a hard request timeout (hung sockets otherwise stall whole batches)."""
    from google import genai
    from google.genai import types

    ensure_gemini_key()
    return genai.Client(http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))
