"""Validate generated tracks against the real geo: volume entry contract, corridor membership, line geometry."""

from __future__ import annotations

# isort: split
from landed_geo import great_circle_dist_nm

import scn_geo
import scn_tracks
from scn_model import Scenario


def track_by_reg(tracks: dict, reg: str) -> dict:
    return next(a for a in tracks["aircraft"] if a["reg"] == reg)


def check_volumes(sc: Scenario, tracks: dict) -> list[str]:
    """Every aircraft enters exactly the volumes the scenario declares (``geo.must_enter`` / ``geo.may_enter``)."""
    errors: list[str] = []
    for a in tracks["aircraft"]:
        entered = scn_geo.volumes_entered(a["points"])
        must = sc.geo.must_enter.get(a["reg"], [])
        may = sc.geo.may_enter.get(a["reg"], [])
        for prefix in must:
            if not any(v.startswith(prefix) for v in entered):
                errors.append(f"{sc.id}/{a['reg']}: must enter {prefix}* but entered {sorted(entered)}")
        for v in entered:
            if not any(v.startswith(p) for p in [*must, *may]):
                errors.append(f"{sc.id}/{a['reg']}: unexpectedly enters protected volume {v}")
    return errors


def check_corridors(sc: Scenario, tracks: dict) -> list[str]:
    """Every point of an aircraft lies within ``corridor_tol_nm`` of one of its declared corridor polygons."""
    errors: list[str] = []
    cors = scn_geo.corridors()
    for reg, ids in sc.geo.corridors.items():
        if not ids:
            continue
        pts = track_by_reg(tracks, reg)["points"]
        worst = 0.0
        for p in pts:
            d = min(scn_geo.min_dist_to_ring_nm(p["lat"], p["lon"], cors[i]["ring"]) for i in ids)
            worst = max(worst, d)
        if worst > sc.geo.corridor_tol_nm:
            errors.append(f"{sc.id}/{reg}: {worst:.2f} nm outside {ids} (tolerance {sc.geo.corridor_tol_nm})")
    return errors


def check_lines(sc: Scenario, tracks: dict) -> list[str]:
    errors: list[str] = []
    refs = scn_geo.reference_points()
    for ln in sc.lines:
        tr = track_by_reg(tracks, ln.aircraft)
        t0, t1 = tr["points"][0]["t"], tr["points"][-1]["t"]
        if not (t0 - 12 <= ln.t <= t1 + 12):
            errors.append(f"{sc.id}/{ln.id}: t={ln.t} outside {ln.aircraft} flight [{t0}, {t1}]")
            continue
        if ln.near:
            pos = scn_tracks.position_at(tr, min(max(ln.t, t0), t1))
            d = great_circle_dist_nm(pos[0], pos[1], *refs[ln.near.ref])
            if d > ln.near.max_nm:
                errors.append(
                    f"{sc.id}/{ln.id}: {ln.aircraft} is {d:.2f} nm from {ln.near.ref} at t={ln.t} "
                    f"(limit {ln.near.max_nm})"
                )
        if ln.t > sc.window_s:
            errors.append(f"{sc.id}/{ln.id}: t={ln.t} beyond window {sc.window_s}")
    return errors


def validate(sc: Scenario, tracks: dict) -> list[str]:
    return check_volumes(sc, tracks) + check_corridors(sc, tracks) + check_lines(sc, tracks)
