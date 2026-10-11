"""Paired exploratory bootstrap for the frozen confirmation comparison."""

import argparse
import json
from pathlib import Path

import jiwer
import numpy as np

from experiment import dump, load_frozen, numeric


def compare(directory, output):
    plan, _manifest, baseline = load_frozen(directory)
    ids = plan["confirmation"]
    arms = {
        name: {r["id"]: r for r in json.loads((directory / f"confirmation-{name}.json").read_text())}
        for name in ("control", "domain")
    }
    if any(set(rows) != set(ids) for rows in arms.values()):
        raise ValueError("Incomplete paired comparison")
    words, errors = [], []
    improved, worsened, tied = 0, 0, 0
    numeric_gained, numeric_lost = 0, 0
    for key in ids:
        reference = baseline[key]["reference"]
        scores = [jiwer.process_words(reference, arms[name][key]["hypothesis"]) for name in ("control", "domain")]
        words.append(scores[0].hits + scores[0].substitutions + scores[0].deletions)
        counts = [score.substitutions + score.deletions + score.insertions for score in scores]
        errors.append(counts[1] - counts[0])
        improved += counts[1] < counts[0]
        worsened += counts[1] > counts[0]
        tied += counts[1] == counts[0]
        if numeric(reference):
            correct = [numeric(reference) == numeric(arms[name][key]["hypothesis"]) for name in ("control", "domain")]
            numeric_gained += correct == [False, True]
            numeric_lost += correct == [True, False]
    rng = np.random.default_rng(41)
    sample = rng.integers(0, len(ids), size=(10000, len(ids)))
    delta = np.asarray(errors)[sample].sum(axis=1) / np.asarray(words)[sample].sum(axis=1)
    dump(
        output,
        {
            "n": len(ids),
            "bootstrap_replicates": 10000,
            "seed": 41,
            "wer_delta_domain_minus_control": sum(errors) / sum(words),
            "bootstrap_95_percentile_interval": np.percentile(delta, [2.5, 97.5]).tolist(),
            "clips_improved": improved,
            "clips_worsened": worsened,
            "clips_tied": tied,
            "numeric_proxy_gained": numeric_gained,
            "numeric_proxy_lost": numeric_lost,
            "caveat": "Exploratory clip bootstrap; source filename groups are disjoint but speaker/session independence and single-run model variability are not established. Includes failed requests as empty hypotheses.",
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    compare(args.directory, args.output)
