"""Extract ~100 ATCO2 clips (data only) from the downloaded parquet to WAV + manifest.

Reads the parquet as plain data; nothing from the dataset is executed.
"""

import io
import json
import random
from pathlib import Path

import pandas as pd
import soundfile as sf

ROOT = Path(__file__).parent
RAW = ROOT / "audio" / "atco2" / "raw" / "test.parquet"
OUT = ROOT / "audio" / "atco2" / "clips"
N = 100


def main() -> None:
    df = pd.read_parquet(RAW)
    df = df[(df["duration"] >= 2.0) & (df["duration"] <= 20.0) & (df["text"].str.split().str.len() >= 4)]
    idx = random.Random(7).sample(range(len(df)), min(N, len(df)))
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in sorted(idx):
        r = df.iloc[i]
        audio, sr = sf.read(io.BytesIO(r["audio"]["bytes"]))
        path = OUT / f"{r['id']}.wav"
        sf.write(path, audio, sr)
        rows.append({"file": str(path.relative_to(ROOT)), "id": r["id"], "text": r["text"],
                     "duration": float(r["duration"])})
    (OUT.parent / "manifest.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    print(len(rows), "clips,", sum(x["duration"] for x in rows) / 60, "min")
    for x in rows[:5]:
        print(x["text"])


if __name__ == "__main__":
    main()
