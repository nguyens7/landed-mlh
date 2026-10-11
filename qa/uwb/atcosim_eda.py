"""Metadata-only ATCOSIM EDA; reads an official local CSV and prints aggregates."""

import argparse
import csv
import hashlib
import json
import re
import statistics
from collections import Counter
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("csv", type=Path)
args = parser.parse_args()
with args.csv.open(newline="", encoding="utf-8-sig") as handle:
    rows = list(csv.DictReader(handle))
texts = [row["transcription"].lower().strip() for row in rows]
durations = [float(row["length_sec"]) for row in rows]
keywords = [
    "helicopter",
    "heli",
    "mayday",
    "pan pan",
    "emergency",
    "visual",
    "vfr",
    "say again",
    "weather",
    "climb",
    "descend",
    "flight level",
]
print(
    json.dumps(
        {
            "source": "https://www2.spsc.tugraz.at/databases/ATCOSIM/TXTdata/fulldata.csv",
            "sha256": hashlib.sha256(args.csv.read_bytes()).hexdigest(),
            "rows": len(rows),
            "hours": sum(durations) / 3600,
            "speakers": dict(Counter(row["speaker_id"] for row in rows)),
            "sessions": len({(row["speaker_id"], row["session_id"]) for row in rows}),
            "duration_median": statistics.median(durations),
            "duration_min": min(durations),
            "duration_max": max(durations),
            "corrupt": dict(Counter(row["recording_corrupt"] for row in rows)),
            "unique_transcripts": len(set(texts)),
            "keyword_utterance_counts": {
                word: sum(
                    bool(re.search(r"\b" + re.escape(word) + r"\b", text))
                    for text in texts
                )
                for word in keywords
            },
        },
        indent=2,
    )
)
