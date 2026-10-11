# Third-party data and attributions

The MIT license in `LICENSE` covers Landed's source code. Data in this repository keeps its own license:

| Data | Where | License |
|---|---|---|
| ADS-B tracks from adsb.lol (live snapshots and the globe_history archive, and replays derived from them) | `eda/data/`, `app/public/data/replay/` | ODbL 1.0, "ADS-B data: adsb.lol" (https://api.adsb.lol/docs) |
| River shoreline polygons from OpenStreetMap | `geo/water_cache/`, `app/public/data/geo/` | ODbL 1.0, "© OpenStreetMap contributors" |
| FAA, eCFR and NTSB facts and procedure data (14 CFR 93 Subpart W, CIFP, plates, AIR-26-02) | `geo/`, `docs/` | U.S. government works |
| ATCO2 and UWB-ATCC speech corpora | not included; used for evaluation only | see `speech/DATA.md` |

No LiveATC audio is used. Prior-art projects (MayDay, Squawk, ACRP miscommunication detection, SESAR HAAWAII) inspired ideas only; no code from them is included.

Landed is a simulation and research prototype. It is not for operational use and never transmits on aviation frequencies.
