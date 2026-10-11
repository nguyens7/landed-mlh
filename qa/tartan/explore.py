"""Bounded official Tartan sample inspection; no provider calls or raw-data publishing."""

import argparse
import ast
import csv
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import soundfile as sf

BASE = "https://airlab-cloud.andrew.cmu.edu:8080/swift/v1/AUTH_ac8533a83cff4d48bc8c608ad222d330"
AUDIO = BASE + "/tartanaviation-audio/kbtp/2020/11/11-14-20_audio.zip"
ADSB = BASE + "/tartanaviation-adsb/kbtp/raw/2020.zip"
MEMBERS = [
    (AUDIO, "11-14-20_audio/6.wav", "paired-audio.wav"),
    (AUDIO, "11-14-20_audio/6.txt", "paired-audio.txt"),
    (ADSB, "11-14-20/1.csv", "paired-adsb.csv"),
    (AUDIO, "11-14-20_audio/26.wav", "secondary-audio.wav"),
    (AUDIO, "11-14-20_audio/26.txt", "secondary-audio.txt"),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RemoteZip(io.RawIOBase):
    """Seekable HTTP range reader with per-request and total transfer limits."""

    def __init__(self, url):
        self.url, self.pos, self.transferred = url, 0, 0
        with urllib.request.urlopen(
            urllib.request.Request(url, method="HEAD"), timeout=30
        ) as response:
            self.size = int(response.headers["Content-Length"])
            self.etag = response.headers.get("ETag")
        self.budget = 16 * 1024 * 1024

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        position = (
            offset
            if whence == 0
            else self.pos + offset
            if whence == 1
            else self.size + offset
        )
        if whence not in (0, 1, 2) or not 0 <= position <= self.size:
            raise ValueError("Invalid ZIP seek")
        self.pos = position
        return position

    def read(self, n=-1):
        n = min(self.size - self.pos, n if n >= 0 else self.size - self.pos)
        if n <= 0:
            return b""
        if n > self.budget - self.transferred:
            raise ValueError("Remote ZIP exceeds 16 MiB transfer budget")
        headers = {"Range": f"bytes={self.pos}-{self.pos + n - 1}"}
        if self.etag:
            headers["If-Match"] = self.etag
        with urllib.request.urlopen(
            urllib.request.Request(self.url, headers=headers), timeout=30
        ) as response:
            expected = f"bytes {self.pos}-{self.pos + n - 1}/{self.size}"
            if (
                response.status != 206
                or response.headers.get("Content-Range") != expected
            ):
                raise ValueError("Server did not honor exact byte range")
            data = response.read(n + 1)
        if len(data) != n:
            raise ValueError("Truncated or oversized range response")
        self.pos += n
        self.transferred += n
        return data


def fetch(directory):
    directory.mkdir(parents=True, exist_ok=True)
    provenance = []
    for url in (AUDIO, ADSB):
        remote = RemoteZip(url)
        with zipfile.ZipFile(remote) as archive:
            for source, member, target in MEMBERS:
                if source != url:
                    continue
                info = archive.getinfo(member)
                if (
                    info.file_size > 20 * 1024 * 1024
                    or info.compress_size > 8 * 1024 * 1024
                ):
                    raise ValueError("Sample member exceeds size limit")
                # Fixed output filenames, never extract archive paths or run downloaded code.
                path = directory / target
                path.write_bytes(archive.read(info))
                provenance.append(
                    {
                        "url": url,
                        "archive_bytes": remote.size,
                        "etag": remote.etag,
                        "member": member,
                        "bytes": info.file_size,
                        "sha256": sha(path),
                    }
                )
    (directory / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


def parse_time(row):
    """Parse legacy Python-list CSV cells without evaluating executable code."""
    date = ast.literal_eval(row["Date"])
    time = ast.literal_eval(row["Time"])
    if (
        not isinstance(date, list)
        or not isinstance(time, list)
        or len(date) != 3
        or len(time) != 3
    ):
        raise ValueError("Expected three date and time components")
    second = float(time[2].removesuffix("Z"))
    if not 0 <= second < 60:
        raise ValueError("Invalid seconds")
    return datetime(
        *map(int, date), int(time[0]), int(time[1]), tzinfo=UTC
    ) + timedelta(seconds=second)


def summarize(directory, stem="paired-audio", member="11-14-20_audio/6.wav"):
    text = (directory / (stem + ".txt")).read_text()
    stamps = re.findall(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+", text)
    start, end = [datetime.fromisoformat(value).replace(tzinfo=UTC) for value in stamps]
    # UTC is supported by the official recording code; actual clock offset is uncalibrated.
    audio, rate = sf.read(directory / (stem + ".wav"), dtype="float32", always_2d=True)
    mono = np.mean(audio, axis=1)
    window = rate // 10
    rms = [
        float(np.sqrt(np.mean(mono[i : i + window] ** 2)))
        for i in range(0, len(mono), window)
    ]
    db = [float(20 * np.log10(max(value, 1e-10))) for value in rms]
    valid, invalid, blank = [], 0, 0
    with (directory / "paired-adsb.csv").open() as source:
        for row in csv.DictReader(source):
            if not any(row.values()):
                blank += 1
                continue
            try:
                stamp = parse_time(row)
                point = {
                    "id": row["ID"],
                    "time": stamp,
                    "lat": float(row["Lat"]),
                    "lon": float(row["Lon"]),
                    "age": float(row["Age"]),
                    "altitude": float(row["Altitude"]),
                }
                if not all(
                    np.isfinite(point[key]) for key in ("lat", "lon", "age", "altitude")
                ):
                    raise ValueError("Nonfinite coordinate or telemetry")
                if not -90 <= point["lat"] <= 90 or not -180 <= point["lon"] <= 180:
                    raise ValueError("Invalid position")
                valid.append(point)
            except (ValueError, SyntaxError, TypeError, KeyError, AttributeError):
                invalid += 1
    selected = [row for row in valid if start <= row["time"] <= end]
    unique = {(p["id"], p["time"], p["lat"], p["lon"]) for p in selected}
    summary = {
        "airport": "KBTP",
        "selection": "two small WAVs on first shared available November day after default sample; exploratory, not random",
        "audio": {
            "member": member,
            "sha256": sha(directory / (stem + ".wav")),
            "metadata_sha256": sha(directory / (stem + ".txt")),
            "sample_rate": rate,
            "channels": audio.shape[1],
            "duration_s": len(audio) / rate,
            "metadata_start_utc": start.isoformat(),
            "metadata_end_utc": end.isoformat(),
            "metadata_duration_s": (end - start).total_seconds(),
            "rms_window_s": 0.1,
            "rms_dbfs_percentiles_10_50_90": np.percentile(db, [10, 50, 90]).tolist(),
            "windows_above_minus30_dbfs": sum(value > -30 for value in db),
            "window_count": len(db),
            "energy_note": "Energy is not a speech detector or verified utterance count.",
        },
        "adsb": {
            "member": MEMBERS[2][1],
            "sha256": sha(directory / "paired-adsb.csv"),
            "valid_rows": len(valid),
            "blank_rows": blank,
            "invalid_nonblank_rows": invalid,
            "first_utc": min(p["time"] for p in valid).isoformat(),
            "last_utc": max(p["time"] for p in valid).isoformat(),
            "aircraft_ids": len({p["id"] for p in valid}),
            "rows_in_audio_window": len(selected),
            "aircraft_ids_in_audio_window": len({p["id"] for p in selected}),
            "unique_position_time_tuples_in_window": len(unique),
            "age_s_range_in_window": [
                min(p["age"] for p in selected),
                max(p["age"] for p in selected),
            ]
            if selected
            else None,
        },
        "alignment": "UTC interval overlap only; recorder clock offset and audio speaker/aircraft association are unverified.",
        "license": "Raw data license scope unresolved; keep downloaded audio, CSV, and per-aircraft tracks private.",
    }
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["fetch", "summarize"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stem", default="paired-audio")
    parser.add_argument("--member", default="11-14-20_audio/6.wav")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.directory)
    else:
        output = (
            json.dumps(summarize(args.directory, args.stem, args.member), indent=2)
            + "\n"
        )
        if args.output:
            args.output.write_text(output)
        else:
            print(output)
