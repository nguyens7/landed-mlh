"""Append-only JSONL audit log: ``{ts, proposal, decision, who, latency_ms}``. Never rewritten."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(
    os.environ.get("LANDED_AUDIT_PATH", Path(__file__).resolve().parents[1] / "audit" / "audit.jsonl")
)


class AuditLog:
    """Only ``append`` and ``read`` exist. The file is opened in append mode and fsynced per entry."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_PATH
        self._lock = threading.Lock()

    def append(
        self, proposal: dict[str, Any], decision: str, who: str, latency_ms: int | None = None
    ) -> dict[str, Any]:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            + f".{int(time.time() * 1000) % 1000:03d}Z",
            "proposal": proposal,
            "decision": decision,
            "who": who,
            "latency_ms": latency_ms,
        }
        line = json.dumps(entry, separators=(",", ":"), default=str) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        return entry

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
