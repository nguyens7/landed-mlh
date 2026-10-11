"""One-off: writes app/public/data/geo/altimeter_KLGA_2026-10-10.json from the IEM
ASOS pull (station LGA, data=alti) for 2026-10-10 local (America/New_York) day.
Source: https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=LGA&data=alti&year1=2026&month1=10&day1=10&year2=2026&month2=10&day2=11&tz=America%2FNew_York&format=onlycomma
Kept as a record of provenance; build.py does not re-run this (no network calls
at build time), it just re-serializes the checked-in rows below.
"""

import json
from pathlib import Path

RAW = """00:51,30.27
01:51,30.29
02:51,30.31
03:51,30.31
04:51,30.32
05:51,30.34
06:51,30.37
07:51,30.39
08:51,30.43
09:51,30.45
10:51,30.46
11:51,30.46
12:51,30.46
13:51,30.43
14:51,30.41
15:51,30.41
16:51,30.41
17:51,30.41
18:51,30.43
19:51,30.44
20:51,30.44
21:51,30.45
22:51,30.45
23:51,30.43"""


def build() -> list[dict]:
    out = []
    for row in RAW.splitlines():
        t, alti = row.split(",")
        out.append({"time": f"2026-10-10T{t}:00-04:00", "altimeter_inhg": float(alti)})
    return out


def main() -> None:
    out_path = (
        Path(__file__).resolve().parent.parent
        / "app/public/data/geo/altimeter_KLGA_2026-10-10.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(build(), indent=1) + "\n")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
