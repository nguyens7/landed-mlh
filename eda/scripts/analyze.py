"""Landed EDA: helicopters around NYC from adsb.lol globe_history (2026-10-10) + live polls (2026-10-11).
All geometry marked APPROX is hand-drawn for EDA only (see README)."""
import json, math, collections, urllib.request, re, os
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

NM = 1852.0
def dm(s):  # '40-46.149755N' -> deg
    d, m = s[:-1].split('-'); v = int(d) + float(m)/60; return -v if s[-1] in 'SW' else v
def xy(lat, lon, lat0=40.75):  # local equirectangular, nm
    return ((np.asarray(lon)+73.95)*60*math.cos(math.radians(lat0)), (np.asarray(lat)-lat0)*60)
def dest(lat, lon, brg, d_nm):
    b = math.radians(brg); return lat + d_nm/60*math.cos(b), lon + d_nm/60*math.sin(b)/math.cos(math.radians(lat))

# --- Cited points ---------------------------------------------------------
# LGA runway ends + true bearings: AirNav KLGA (https://www.airnav.com/airport/KLGA)
R22_THR = (dm('40-47.126200N'), dm('073-52.240402W'))  # rwy 22 end (land 212 true)
R31_THR = (dm('40-46.324287N'), dm('073-51.426695W'))  # rwy 31 end (land 302 true)
TDZE = 12  # ft, approx (AirNav elevations 11-21 ft)
HELIPORTS = {  # AirNav, see SPEC §1.1
    '6N5 E34th St': (40.7424472, -73.9721222), 'JRB Downtown': (40.7012136, -74.0090283),
    'NJ87 Univ Hosp Newark': (dm('40-44.450833N'), dm('074-11.450500W')),
    'NY52 SIUH': (40.5842028, -74.0832611)}
# APPROX corridor centerlines (hand-drawn from landmarks, NOT the legal SFRA boundary)
HUDSON = [(40.607,-74.040),(40.689,-74.046),(40.703,-74.022),(40.765,-74.002),(40.851,-73.955),(40.962,-73.913)]
EAST = [(40.689,-74.016),(40.706,-73.997),(40.713,-73.972),(40.742,-73.969),(40.772,-73.940)]
# Approach centerlines: 22 straight-in 10 nm (COPTER ILS 22 course 224 mag ~ 212 true);
# 31: RNAV X 31 is a CURVED visual final -> modeled as straight 3 nm on 122 true (APPROX, understates)
APP = {'LGA22': (R22_THR, 32.0, 10.0), 'LGA31': (R31_THR, 122.0, 3.0)}

def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx-ax, by-ay; L2 = dx*dx+dy*dy
    t = np.clip(((px-ax)*dx+(py-ay)*dy)/L2, 0, 1); return np.hypot(px-(ax+t*dx), py-(ay+t*dy)), t
def poly_dist(px, py, line):
    xs, ys = xy([p[0] for p in line], [p[1] for p in line])
    return np.min([seg_dist(px, py, xs[i], ys[i], xs[i+1], ys[i+1])[0] for i in range(len(xs)-1)], axis=0)

# --- Load history ---------------------------------------------------------
rows = []; meta = {}
for line in open('data/history_nyc_traces.jsonl'):
    d = json.loads(line); cat = None; flights = set()
    for p in d['pts']:
        if len(p) > 8 and isinstance(p[8], dict):
            cat = cat or p[8].get('category'); f = (p[8].get('flight') or '').strip(); f and flights.add(f)
    meta[d['icao']] = dict(reg=d['r'], type=d['t'], desc=d['desc'], cat=cat, flights=' '.join(sorted(flights)))
    if cat != 'A7': continue
    for p in d['pts']:
        alt = p[3]; geom = p[10] if len(p) > 10 else None
        rows.append(dict(icao=d['icao'], ts=d['base_ts']+p[0], lat=p[1], lon=p[2],
                         alt_baro=None if alt in (None, 'ground') else alt, ground=alt == 'ground',
                         alt_geom=geom, gs=p[4], src=p[9] if len(p) > 9 else None))
H = pd.DataFrame(rows); H['t'] = pd.to_datetime(H.ts, unit='s', utc=True).dt.tz_convert('America/New_York')
M = pd.DataFrame.from_dict(meta, orient='index')
print('aircraft in NYC box:', len(M), M.cat.value_counts(dropna=False).to_dict())

# --- Owner lookup (FAA registry, public) for medevac flags ---------------
own_f = 'data/faa_owner_cache.json'; own = json.load(open(own_f)) if os.path.exists(own_f) else {}
for ic, r in M[M.cat == 'A7'].iterrows():
    n = r.reg
    if not n or not str(n).startswith('N') or n in own: continue
    try:
        html = urllib.request.urlopen(urllib.request.Request(
            f'https://registry.faa.gov/AircraftInquiry/Search/NNumberResult?nNumberTxt={n}',
            headers={'User-Agent': 'Mozilla/5.0'}), timeout=15).read().decode('utf8', 'ignore')
        m = re.search(r'data-label="Name"[^>]*>\s*([^<]+)', html); own[n] = m.group(1).strip() if m else None
    except Exception as e: own[n] = None
json.dump(own, open(own_f, 'w'), indent=1)
MED_KW = re.compile(r'MEDEVAC|MED|LIFE|AIR METHODS|PHI|HOSPITAL|HEALTH|EMS|AMBUL|STAT|NORTHWELL|HACKENSACK|METRO AVIATION|AEROMED', re.I)
HEL = M[M.cat == 'A7'].copy(); HEL['owner'] = HEL.reg.map(own)
HEL['medevac_flag'] = HEL.apply(lambda r: bool(MED_KW.search(f"{r.owner or ''} {r.flights}")), axis=1)
HEL['role_guess'] = np.where(HEL.owner.fillna('').str.contains('POLICE'), 'police',
                     np.where(HEL.medevac_flag, 'medevac?', 'other/charter/tour/private'))
g = H.groupby('icao'); HEL['n_pts'] = g.size(); HEL['first'] = g.t.min(); HEL['last'] = g.t.max()
HEL['max_alt_baro'] = g.alt_baro.max(); HEL.to_csv('data/helicopters_2026-10-10.csv')
print(HEL[['reg','type','flights','owner','role_guess','n_pts']].to_string())

# --- Corridor membership + altitude vs ceilings ---------------------------
px, py = xy(H.lat.values, H.lon.values)
H['d_hudson'] = poly_dist(px, py, HUDSON); H['d_east'] = poly_dist(px, py, EAST)
H['corridor'] = np.where(H.d_hudson < 0.35, 'Hudson', np.where(H.d_east < 0.25, 'East River', 'other'))
# NOTE alt_baro = pressure altitude (29.92), NOT MSL; alt_geom = GNSS height (WGS84 ellipsoid; NYC geoid ~ -32 m => ~+105 ft vs MSL)
H['alt_geom_msl'] = H.alt_geom - 105
fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
for a, (c, ceil) in zip(ax, [('Hudson', [1300]), ('East River', [1500, 1100])]):
    s = H[(H.corridor == c)]
    a.hist(s.alt_baro.dropna(), bins=range(0, 3000, 100), alpha=.6, label='alt_baro (pressure alt)')
    a.hist(s.alt_geom_msl.dropna(), bins=range(0, 3000, 100), alpha=.6, label='alt_geom − 105 ft (≈MSL)')
    for v in ceil: a.axvline(v, color='r', ls='--'); a.text(v+20, a.get_ylim()[1]*.9, f'{v} ft', color='r')
    a.set_title(f'{c} corridor (APPROX), n={len(s)} pts, {s.icao.nunique()} helos'); a.set_xlabel('ft'); a.legend(fontsize=7)
fig.suptitle('Helicopter altitudes vs SFRA ceilings, 2026-10-10 (adsb.lol globe_history)'); fig.tight_layout()
fig.savefig('figures/alt_vs_ceilings.png', dpi=130)
cs = H[H.corridor != 'other'].groupby('corridor').apply(lambda s: pd.Series({
    'pts': len(s), 'helos': s.icao.nunique(),
    'pct_baro_gt_1300': (s.alt_baro > 1300).mean()*100, 'pct_geom_gt_1300': (s.alt_geom_msl > 1300).mean()*100,
    'pct_baro_gt_1100': (s.alt_baro > 1100).mean()*100, 'median_baro': s.alt_baro.median()}))
print(cs.round(1).to_string())

# --- Approach proximity ----------------------------------------------------
res = []
for name, (thr, brg, L) in APP.items():
    end = dest(*thr, brg, L); ax_, ay_ = xy(thr[0], thr[1]); bx_, by_ = xy(*end)
    d, t = seg_dist(px, py, ax_, ay_, bx_, by_)
    H[f'd_{name}'] = d; H[f'gp_{name}'] = TDZE + t*L*318.0  # 3-degree glidepath ~318 ft/nm
    H[f'v_{name}'] = H.alt_geom_msl.fillna(H.alt_baro) - H[f'gp_{name}']
    near = H[(H[f'd_{name}'] < 1.0) & (~H.ground)]
    for ic, s in near.groupby('icao'):
        i = s[f'd_{name}'].idxmin()
        res.append(dict(approach=name, reg=HEL.reg.get(ic), type=HEL.type.get(ic), role=HEL.role_guess.get(ic),
                        min_lat_nm=round(s.loc[i, f'd_{name}'], 2), along_nm=round(float(np.hypot(px[H.index.get_loc(i)]-ax_, py[H.index.get_loc(i)]-ay_)), 2),
                        heli_alt_ft=s.loc[i, 'alt_geom_msl'] if pd.notna(s.loc[i, 'alt_geom_msl']) else s.loc[i, 'alt_baro'],
                        glidepath_ft=round(s.loc[i, f'gp_{name}']), vert_sep_ft=round(s.loc[i, f'v_{name}']),
                        time=s.loc[i, 't'].strftime('%H:%M:%S')))
P = pd.DataFrame(res).sort_values(['approach', 'min_lat_nm']); P.to_csv('data/approach_proximity.csv', index=False)
print(P.to_string(index=False))

# --- Map -------------------------------------------------------------------
fig, a = plt.subplots(figsize=(9, 10))
colors = {'police': 'tab:blue', 'medevac?': 'tab:red', 'other/charter/tour/private': 'tab:gray'}
for ic, s in H.groupby('icao'):
    a.plot(s.lon, s.lat, '-', lw=.6, alpha=.7, color=colors[HEL.role_guess[ic]])
for line, lab in [(HUDSON, 'Hudson (approx)'), (EAST, 'East River (approx)')]:
    a.plot([p[1] for p in line], [p[0] for p in line], 'c-', lw=6, alpha=.25, label=lab)
for name, (thr, brg, L) in APP.items():
    e = dest(*thr, brg, L); a.plot([thr[1], e[1]], [thr[0], e[0]], 'r-', lw=2.5, label=f'{name} approach (approx)')
for k, (la, lo) in HELIPORTS.items():
    a.plot(lo, la, 'k^'); a.text(lo+.005, la, k, fontsize=7)
for k, c in colors.items(): a.plot([], [], color=c, label=f'helo: {k}')
a.set_xlim(-74.25, -73.70); a.set_ylim(40.55, 40.95); a.set_aspect(1/math.cos(math.radians(40.75)))
a.legend(fontsize=7, loc='lower right'); a.set_title(f'Helicopter tracks NYC, 2026-10-10 (adsb.lol, ODbL) — {H.icao.nunique()} helos')
fig.tight_layout(); fig.savefig('figures/map_tracks.png', dpi=140)
# zoom LGA
a.set_xlim(-74.05, -73.75); a.set_ylim(40.68, 40.90); fig.savefig('figures/map_tracks_lga_zoom.png', dpi=140)

# --- Proximity scatter -----------------------------------------------------
fig, a = plt.subplots(figsize=(7, 5))
for name, mk in [('LGA22', 'o'), ('LGA31', 's')]:
    s = H[(H[f'd_{name}'] < 2) & (~H.ground)]
    a.scatter(s[f'd_{name}'], s[f'v_{name}'], s=4, marker=mk, alpha=.4, label=name)
a.axhline(0, color='k', lw=.8); a.axvline(0.5, color='r', ls='--', lw=.8); a.axhspan(-500, 500, color='r', alpha=.07)
a.set_xlabel('lateral distance to approach centerline (nm)'); a.set_ylabel('helo alt − 3° glidepath alt (ft)')
a.set_title('First-pass conflict geometry (approx paths), 2026-10-10'); a.legend()
fig.tight_layout(); fig.savefig('figures/approach_proximity.png', dpi=130)

# --- Data quality ----------------------------------------------------------
Hs = H.sort_values(['icao', 'ts']); Hs['dt'] = Hs.groupby('icao').ts.diff()
q = dict(points=len(H), helos=H.icao.nunique(),
         median_dt_s=float(Hs.dt.median()), p90_dt_s=float(Hs.dt.quantile(.9)),
         gaps_gt_60s=int((Hs.dt > 60).sum()), pct_alt_baro_missing=float(H.alt_baro.isna().mean()*100),
         pct_on_ground=float(H.ground.mean()*100), pct_alt_geom_missing=float(H.alt_geom.isna().mean()*100),
         src_counts=H.src.value_counts().to_dict())
fig, a = plt.subplots(figsize=(6, 4)); a.hist(Hs.dt.dropna().clip(upper=120), bins=60)
a.set_yscale('log'); a.set_xlabel('seconds between trace points (clipped 120)'); a.set_title('Helicopter trace update interval')
fig.tight_layout(); fig.savefig('figures/update_interval.png', dpi=130)
# live polls
live = [json.loads(l) for l in open('data/adsblol_snapshots.jsonl')]
ok = [d for d in live if 'ac' in d]
lc = collections.Counter(a.get('category') for d in ok for a in d['ac'])
lh = {a.get('hex') for d in ok for a in d['ac'] if a.get('category') == 'A7'}
q['live_polls'] = len(live); q['live_poll_errors'] = len(live)-len(ok); q['live_unique_aircraft'] = len({a.get('hex') for d in ok for a in d['ac']})
q['live_helos'] = len(lh); q['live_cat_counts'] = dict(lc)
json.dump(q, open('data/quality.json', 'w'), indent=1, default=str); print(json.dumps(q, indent=1, default=str))
