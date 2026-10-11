"""Offline tests for cost bounds, segmentation, and score accounting."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from experiment import (
    RESERVATION,
    Budget,
    boundaries,
    digest,
    freeze,
    load_frozen,
    measure,
    prepare,
    validate_local,
)


class ExperimentGuards(unittest.TestCase):
    def test_budget_survives_restart_and_rejects_before_request(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "budget.json"
            Budget(path, ceiling=RESERVATION).reserve("first")
            with self.assertRaises(RuntimeError):
                Budget(path, ceiling=RESERVATION).reserve("second")
            self.assertEqual(len(json.loads(path.read_text())["reservations"]), 1)

    def test_segmentation_keeps_padding_and_internal_silence(self):
        values = np.zeros(3000, dtype=np.float32)
        values[500:800] = 0.1
        values[2200:2400] = 0.1
        self.assertEqual(boundaries(values, 1000), (250, 2650))

    def test_silent_or_short_activity_passes_through(self):
        self.assertEqual(boundaries(np.zeros(2000), 1000), (0, 2000))
        with self.assertRaises(ValueError):
            boundaries(np.array([float("nan")]), 1000)

    def test_numeric_proxy_denominator_requires_reference_digits(self):
        baseline = {"a": {"reference": "hello"}, "b": {"reference": "heading 060"}}
        rows = [
            {"id": "a", "hypothesis": "hello", "latency_s": 1},
            {
                "id": "b",
                "hypothesis": "heading 020",
                "latency_s": 2,
                "error": "failure",
            },
        ]
        result = measure(rows, baseline)
        self.assertEqual(result["numeric_sequence_proxy"], {"eligible": 1, "exact": 0})
        self.assertEqual(result["errors"], 1)
        self.assertAlmostEqual(result["wer"], 1 / 3)

    def test_existing_experiment_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "sentinel").write_text("existing")
            with self.assertRaises(ValueError):
                prepare(path, path / "missing-source")

    def test_latency_excludes_cached_and_failed_calls(self):
        baseline = {key: {"reference": "hello"} for key in ("a", "b", "c")}
        rows = [
            {"id": "a", "hypothesis": "hello", "latency_s": 1},
            {"id": "b", "hypothesis": "hello", "latency_s": 100, "cached": True},
            {"id": "c", "hypothesis": "", "latency_s": 1000, "error": "timeout"},
        ]
        result = measure(rows, baseline)
        self.assertEqual(result["uncached_success_median_latency_s"], 1)
        self.assertEqual(result["uncached_success_latency_n"], 1)
        self.assertEqual(result["stored_success_latency_n"], 2)
        self.assertEqual(result["cached_results"], 1)

    def test_local_resume_rejects_duplicates_and_identity_or_text_changes(self):
        identity = {"weights": "pinned", "settings": {"beam": 5}}
        row = {
            "id": "a",
            "text": "hello",
            "hypothesis": "hello",
            "error": None,
            "input_sha256": "pcm",
            "identity_sha256": digest(json.dumps(identity, sort_keys=True).encode()),
        }
        manifest = [{"id": "a", "pcm_sha256": "pcm"}]
        validate_local([row], manifest, identity)
        for invalid in (
            [row, row],
            [dict(row, id="other")],
            [dict(row, input_sha256="changed")],
            [dict(row, identity_sha256="changed")],
            [dict(row, hypothesis="different")],
        ):
            with self.assertRaises(ValueError):
                validate_local(invalid, manifest, identity)
        with self.assertRaises(ValueError):
            validate_local([row], manifest, {"weights": "different"})

    def test_frozen_metadata_and_pcm_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            audio = path / "audio.wav"
            sf.write(audio, np.zeros(100, dtype=np.float32), 1000, subtype="PCM_16")
            values, rate = sf.read(audio, dtype="float32")
            pcm_hash = digest(str((rate, values.shape)).encode() + values.astype("<f4").tobytes())
            ids = [str(i) for i in range(150)]
            manifest = [{"id": key, "text": "hello", "file": str(audio), "pcm_sha256": pcm_hash} for key in ids]
            plan = {
                "audit_development": ids[:25],
                "confirmation": ids[25:100],
                "reserve": ids[100:],
            }
            for name, data in [
                ("plan.json", plan),
                ("manifest.json", manifest),
                ("baseline.json", {key: {"reference": "hello"} for key in ids}),
            ]:
                (path / name).write_text(json.dumps(data))
            freeze(path)
            original = (path / "plan.json").read_text()
            (path / "plan.json").write_text(original + " ")
            with self.assertRaisesRegex(ValueError, "Frozen experiment input changed"):
                load_frozen(path)
            (path / "plan.json").write_text(original)
            sf.write(audio, np.ones(100, dtype=np.float32) * 0.1, 1000, subtype="PCM_16")
            with self.assertRaisesRegex(ValueError, "Frozen PCM changed"):
                load_frozen(path)


if __name__ == "__main__":
    unittest.main()
