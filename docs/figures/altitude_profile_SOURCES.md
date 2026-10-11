# Altitude profile: number sources

Every number on `altitude_profile.png` and `altitude_profile.svg`, with its source.
Altitudes are feet MSL unless noted. "Verified" means fetched or read in this pass;
"search snippet" means the figure came from a search result and was not opened.

## Skyline (schematic bars)

| Chart label | Value | Source | Status |
|---|---|---|---|
| One World Trade Center, spire | 1,776 ft | CTBUH height ruling, via https://iit.edu/news/ctbuh-affirms-one-world-trade-center-height and https://skyscraper.org/supertall/?p=5199 | Search snippet |
| One World Trade Center, roof | 1,368 ft | Same | Search snippet |
| Central Park Tower | 1,550 ft (architectural) | CTBUH Skyscraper Center, https://www.skyscrapercenter.com/building/central-park-tower/14269 | Search snippet |
| 432 Park Avenue | **1,397 ft** (architectural and tip) | CTBUH Skyscraper Center, https://www.skyscrapercenter.com/building/wd/13227 | Verified (fetched). **Corrected from the brief's 1,396 ft**, which is Wikipedia's figure |
| Empire State Building, tip | 1,454 ft | CTBUH Skyscraper Center, https://www.skyscrapercenter.com/building/empire-state-building/261 | Verified (fetched) |
| Empire State Building, roof | 1,250 ft (CTBUH "architectural") | Same page | Verified (fetched). Labeled "roof" in the chart |

## Helicopter corridors

| Chart label | Value | Source | Status |
|---|---|---|---|
| Hudson River Exclusion ceiling | 1,300 ft | `app/public/data/geo/corridors.geojson`, feature `sfra_hudson`; 14 CFR 93.350 on eCFR (https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-93/subpart-W) | Read from file |
| Class B floor over the Hudson | 1,300 ft | FAA final rule FR Doc 2026-15552, Amendment of Class B Airspace; New York, NY, Area K floor 1,300 ft MSL (https://www.federalregister.gov/documents/2026/07/31/2026-15552/amendment-of-class-b-airspace-new-york-ny, published 2026-07-31, effective 2026-10-29); Hudson Exclusion defined up to that floor in 14 CFR 93.350 on eCFR (https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-93/subpart-W) | Verified (#29 item 1) |
| Transit 1,000 ft and above; local ops below 1,000 ft | 1,000 ft | `corridors.geojson` `direction_rule` for `sfra_hudson`: "1,000 ft MSL or higher" | Read from file. `altitude_rules.json` does not exist on any branch, so this is the only source |
| East River Exclusion, south band ceiling | 1,500 ft | `corridors.geojson`, `sfra_east_river_south`; 14 CFR 93.350(c), https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-93/subpart-W | Read from file |
| East River Exclusion, north band ceiling | 1,100 ft | `corridors.geojson`, `sfra_east_river_north`; 14 CFR 93.350(c), https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-93/subpart-W | Read from file |

The corridor shapes are digitized approximations (`approximate: true` in the file).
Only the ceilings are charted here.

## Real helicopters, Sat Oct 10 2026, 11:00 to 11:15 ET

- Source: `app/public/data/replay/saturday.json`, adsb.lol globe_history, ODbL.
- 17 aircraft, excluding the simulated entry. Each bar runs from the aircraft's minimum to maximum `alt_ft_msl` in the window. The dot is the median.
- Altitudes are already corrected to the KLGA altimeter (`alt_baro + (altimeter_inhg - 29.92) * 1000`) per the file's metadata.
- Range in the data: about 1 ft to 2,140 ft. The top of the chart is 2,200 ft.

## LGA Rwy 22 final

| Chart element | Value | Source | Status |
|---|---|---|---|
| Threshold elevation (TDZE) | 11.5 ft | `app/public/data/geo/approach_paths.geojson`, runway 22 `tdze_ft`; AirNav KLGA | Read from file |
| Glidepath angle | 3.0 degrees | `approach_paths.geojson` `glidepath_deg`; COPTER ILS/LOC RWY 22 plate, https://aeronav.faa.gov/d-tpp/2609/00289copteril22.pdf | Read from file |
| Glidepath slope | 318 ft per nm | Computed: tan(3 deg) × 6,076.12 ft/nm = 318.5 | Derived |
| Final protected volume, by nm segment | 0–1 nm: 0–730 ft; 1–2 nm: 0–1,048; 2–3 nm: 248–1,367; 3–4 nm: 567–1,685; 4–5 nm: 885–2,004; 5–6 nm: 1,204–2,641 | `app/public/data/geo/protected_volumes.geojson`, `lga22_final_seg0`–`seg5` | Read from file. **Approximate**: the file says the width and the per-segment floor/ceiling split are the project's modeling, not the plate's airspace |
| Simulated medevac N312LM | 600 ft at 1.1 nm from threshold | Scenario parameter from the pitch brief | Brief, not data (see note below) |

**Note on N312LM.** The brief places N312LM at 600 ft, 1.1 nm out. The file
`app/public/data/replay/sim_medevac.json` is a scripted track ("Fictional scripted
track for SPEC.md section 4 scenario S2. Not real ADS-B") that is at 1,500 ft at
about 1.1 nm. That file was not used. The 600 ft figure is inside the 1–2 nm
protected-volume ceiling (1,048 ft), so the chart's point holds. At 1.1 nm the 3°
glidepath is about 360 to 410 ft (TDZE 11.5 ft + 318 ft/nm x 1.1 nm, plus a typical
threshold crossing height), so the medevac sits about 200 ft above the glidepath
and inside the protected volume, not on the glidepath line.

## DCA parallel (Jan 29, 2025)

| Chart text | Value | Source | Status |
|---|---|---|---|
| Collision date and location on final | Jan 29, 2025; Army helicopter and CRJ on final to Runway 33 | NTSB press release, https://www.ntsb.gov/news/press-releases/Pages/NR20250311.aspx ("on final approach to DCA's Runway 33") | Verified (fetched) |
| "American Eagle CRJ" | Operator branding | Brief. NTSB final report AIR-26-02 names PSA Airlines Flight 5342 (https://www.ntsb.gov/investigations/AccidentReports/Reports/AIR2602.pdf) | Brief wording; NTSB operator name not opened |
| Route 4 maximum authorized altitude | 200 ft | NTSB press release, Mar 11, 2025: "helicopters transiting the Route 4 helicopter corridor at the maximum authorized altitude of 200 feet" | Verified (fetched). The quote does not say "msl" |

**Omitted, not verified:**
- Army helicopter altitude at impact (278 ft). It appears in press coverage of the NTSB chair's remarks, but the NTSB briefing PDF (https://www.ntsb.gov/investigations/Documents/Feb.14.2025_Briefing_Mid-air_Collision%20near%20DCA.pdf) could not be read, and no primary page was found that states it. Left out.
- CRJ altitude at impact (about 300 to 325 ft in press reports). Sources conflict. Left out.
- The preliminary report (DCA25MA108) could not be read. The `DCA25MM089` docket number from the brief did not resolve.

## Cruise context

| Chart text | Value | Source | Status |
|---|---|---|---|
| "Jet airliners typically cruise above 30,000 ft" | above 30,000 ft | General statement, replaces the unsourced 35,000 ft figure (#29) | Softened wording; no single primary figure exists |
| "About 17 times One WTC" | 30,000 / 1,776 ≈ 16.9 | Computed | Derived |

## Title and footer

- The title says "the same 2,000 feet." The chart's real traffic runs to about 2,140 ft, and the Class B floor is 1,300 ft. The title is a rounded summary of the 0–2,200 ft scale.
- Footer: "ADS-B: adsb.lol (ODbL)." adsb.lol data is ODbL. Attribution is required.

## Frequencies

The chart shows no CTAF frequencies. If 123.05 (Hudson) or 123.075 (East River) are added to a slide, **verify on the current NY Helicopter Route Chart / TAC** first (14 CFR 93.351(c) defers to the chart; see #29 item 2).
