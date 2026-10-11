"""Verify reference blindness and no extra paid attempts during resume."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

import assisted_audit
from experiment import RESERVATION, Budget


class AssistedAuditGuards(unittest.TestCase):
    def fixture(self, root):
        source, output = root / "source", root / "audit"
        source.mkdir()
        (source / "freeze.json").write_text("{}\n")
        (source / "budget.json").write_text(json.dumps({"reservations": [{"max_usd": RESERVATION}] * 242}))
        ids = [f"private-filename-{i}" for i in range(25)]
        rows = []
        for index, key in enumerate(ids):
            path = source / f"audio-{index}.wav"
            sf.write(path, np.full(800, index / 100, dtype=np.float32), 8000, subtype="PCM_16")
            rows.append({"id": key, "file": str(path), "pcm_sha256": "fixed-pcm"})
        return (
            source,
            output,
            ({"audit_development": ids}, rows, {key: {"reference": "DO NOT SEND GOLD"} for key in ids}),
        )

    def test_blind_requests_and_completed_results_are_never_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output, frozen = self.fixture(Path(temp))
            usage = SimpleNamespace(model_dump=lambda **_: {"prompt_token_count": 250, "candidates_token_count": 100})
            response = SimpleNamespace(
                usage_metadata=usage,
                candidates=[SimpleNamespace(finish_reason="STOP")],
                text=json.dumps(
                    {"transcript": "hello", "languages": ["en"], "spans": [], "fields": [], "cautions": []}
                ),
            )
            client = MagicMock()
            client.models.generate_content.return_value = response
            with (
                patch.object(assisted_audit, "load_frozen", return_value=frozen),
                patch("keys.ensure_gemini_key"),
                patch("google.genai.Client", return_value=client),
                patch("builtins.print"),
            ):
                assisted_audit.run(source, output)
                assisted_audit.run(source, output)
            self.assertEqual(client.models.generate_content.call_count, 25)
            for index, call in enumerate(client.models.generate_content.call_args_list):
                contents = call.kwargs["contents"]
                self.assertEqual(len(contents), 2)
                self.assertEqual(contents[0].inline_data.data, (source / f"audio-{index}.wav").read_bytes())
                self.assertEqual(contents[1], assisted_audit.PROMPT)
                self.assertNotIn("DO NOT SEND GOLD", str(contents))
                self.assertNotIn("private-filename", str(contents))
            ledger = json.loads((output / "budget.json").read_text())
            self.assertEqual(len(ledger["reservations"]), 25)
            self.assertLess(267 * RESERVATION, 10)

    def test_unknown_reserved_attempt_stops_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output, frozen = self.fixture(Path(temp))
            output.mkdir()
            with patch.object(assisted_audit, "load_frozen", return_value=frozen):
                expected = assisted_audit.protocol(source)
                assisted_audit.dump(output / "protocol.json", expected)
                key = assisted_audit.digest(
                    (source / "audio-0.wav").read_bytes() + (output / "protocol.json").read_bytes()
                )
                Budget(output / "budget.json").reserve(key)
                client = MagicMock()
                with (
                    patch("keys.ensure_gemini_key"),
                    patch("google.genai.Client", return_value=client),
                    patch("builtins.print"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "Previously reserved attempt"):
                        assisted_audit.run(source, output)
                client.models.generate_content.assert_not_called()


if __name__ == "__main__":
    unittest.main()
