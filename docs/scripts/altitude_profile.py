"""Render the Landed side-view altitude diagram.

Writes docs/figures/altitude_profile.png (1920x1080) and .svg.

Inputs:
- Helicopter altitudes: app/public/data/replay/saturday.json (adsb.lol ODbL),
  or the path given with --replay.
- Every other number is a constant below, each with its source in
  docs/figures/altitude_profile_SOURCES.md.

Run: uv run python altitude_profile.py [--replay PATH]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle

HERE = Path(__file__).resolve().parent
FIG_DIR = HERE.parent / "figures"
DEFAULT_REPLAY = HERE.parents[1] / "app/public/data/replay/saturday.json"

# Dark-surface palette: dataviz reference palette, dark steps.
SURFACE = "#1a1a19"
TEXT = "#ffffff"
TEXT_2 = "#c3c2b7"
GRID = "#34342f"
BUILDING = "#6d6c66"
BLUE = "#3987e5"  # categorical slot 1: Hudson exclusion, LGA 22 volume
ORANGE = "#d95926"  # categorical slot 2: East River exclusion
AQUA = "#199e70"  # categorical slot 3: real helicopters
CRITICAL = "#e66767"  # status red, reserved for the medevac conflict

# Sourced constants (see altitude_profile_SOURCES.md).
CLASS_B_FLOOR_FT = 1300  # NY Class B Area K floor, FR Doc 2026-15552; corridors.geojson
TRANSIT_FLOOR_FT = 1000  # corridors.geojson sfra_hudson direction_rule
HUDSON_CEILING_FT = 1300  # corridors.geojson sfra_hudson
EAST_RIVER_S_CEILING_FT = 1500  # corridors.geojson sfra_east_river_south
EAST_RIVER_N_CEILING_FT = 1100  # corridors.geojson sfra_east_river_north

# (short label, roof or architectural ft, tip ft, label text)
SKYLINE = [
    ("One WTC", 1368, 1776, "1,776 ft spire\nroof 1,368 ft"),
    ("Central\nPark Tower", 1550, 1550, "1,550 ft"),
    ("432\nPark Ave", 1397, 1397, "1,397 ft"),
    ("Empire\nState", 1250, 1454, "1,454 ft tip\nroof 1,250 ft"),
]

# LGA Rwy 22 final: tdze_ft 11.5 and glidepath_deg 3.0 from approach_paths.geojson.
# Slope = tan(3 deg) * 6076.12 ft per nm.
TDZE_FT = 11.5
GLIDE_DEG = 3.0
FT_PER_NM = 6076.12
GLIDE_FT_PER_NM = math.tan(math.radians(GLIDE_DEG)) * FT_PER_NM

# lga22_final_seg* from protected_volumes.geojson: (start nm, end nm, floor, ceil)
PROTECTED_22 = [
    (0, 1, 0, 730),
    (1, 2, 0, 1048),
    (2, 3, 248, 1367),
    (3, 4, 567, 1685),
    (4, 5, 885, 2004),
    (5, 6, 1204, 2641),
]

# Simulated scenario from the pitch brief: N312LM at 600 ft, crossing the Rwy 22 final 1.1 nm out (replay/build_replay.py).
MEDEVAC_NM = 1.1
MEDEVAC_FT = 600

Y_MAX = 2200

# Left-panel x positions, spaced so two-line labels do not collide.
SKY_X = [0.0, 1.9, 3.8, 5.7]
CORR_X = [8.4, 10.0, 11.6]
HELI_X = 13.7


def load_helicopters(path: Path) -> list[dict[str, float]]:
    """Return min, median and max altitude per real helicopter, low to high."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, float]] = []
    for ac in data["aircraft"]:
        if ac.get("simulated"):
            continue
        alts = [
            p["alt_ft_msl"] for p in ac["points"] if p.get("alt_ft_msl") is not None
        ]
        if not alts:
            continue
        rows.append(
            {
                "min": float(min(alts)),
                "med": float(median(alts)),
                "max": float(max(alts)),
            }
        )
    rows.sort(key=lambda r: r["med"])
    return rows


def style_axes(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=TEXT_2, labelsize=17, length=0)
    ax.grid(axis="y", color=GRID, linewidth=1, zorder=0)
    ax.set_axisbelow(True)


def draw_skyline(ax: plt.Axes) -> None:
    half = 0.45
    for x, (_, roof, tip, label) in zip(SKY_X, SKYLINE, strict=True):
        ax.add_patch(Rectangle((x - half, 0), 2 * half, roof, color=BUILDING, zorder=2))
        if tip > roof:
            ax.plot([x, x], [roof, tip], color=BUILDING, linewidth=4, zorder=2)
        ax.text(
            x, tip + 40, label, ha="center", va="bottom", color=TEXT,
            fontsize=17, linespacing=1.15, zorder=5,
        )  # fmt: skip


def draw_corridors(ax: plt.Axes) -> None:
    cols = [
        (HUDSON_CEILING_FT, BLUE, "1,300 ft\n(Class B)"),
        (EAST_RIVER_S_CEILING_FT, ORANGE, "1,500 ft"),
        (EAST_RIVER_N_CEILING_FT, ORANGE, "1,100 ft"),
    ]
    half = 0.45
    for x, (ceil, color, label) in zip(CORR_X, cols, strict=True):
        ax.add_patch(Rectangle((x - half, 0), 2 * half, ceil, color=color,
                               alpha=0.3, zorder=1))  # fmt: skip
        ax.add_patch(Rectangle((x - half, 0), 2 * half, ceil, fill=False,
                               edgecolor=color, linewidth=2, zorder=2))  # fmt: skip
        ax.text(x, ceil + 40, label, ha="center", va="bottom", color=TEXT,
                fontsize=17, linespacing=1.15, zorder=5)  # fmt: skip
    hx = CORR_X[0]
    ax.plot([hx - half, hx + half], [TRANSIT_FLOOR_FT] * 2, color=TEXT,
            linewidth=2, zorder=3)  # fmt: skip
    ax.text(hx - half - 0.1, TRANSIT_FLOOR_FT - 40, "transit\n1,000+ ft",
            ha="right", va="top", color=TEXT_2, fontsize=15, linespacing=1.1,
            zorder=5)  # fmt: skip
    ax.text(hx - half - 0.1, 380, "local ops\n<1,000 ft", ha="right", va="center",
            color=TEXT_2, fontsize=15, linespacing=1.1, zorder=5)  # fmt: skip


def draw_helicopters(ax: plt.Axes, rows: list[dict[str, float]]) -> None:
    n = len(rows)
    span = 1.8
    for k, r in enumerate(rows):
        x = HELI_X + (k / max(n - 1, 1) - 0.5) * span
        ax.plot([x, x], [r["min"], r["max"]], color=AQUA, linewidth=2.2,
                solid_capstyle="round", zorder=3)  # fmt: skip
        ax.plot([x], [r["med"]], marker="o", markersize=9, color=AQUA,
                markeredgecolor=SURFACE, markeredgewidth=2, zorder=4)  # fmt: skip


def draw_left(ax: plt.Axes, heli: list[dict[str, float]]) -> None:
    style_axes(ax)
    draw_skyline(ax)
    draw_corridors(ax)
    draw_helicopters(ax, heli)
    ax.set_xlim(-1.6, 15.0)
    ax.set_ylim(0, Y_MAX)
    ax.set_yticks([0, 500, 1000, 1500, 2000])
    ax.set_yticklabels(["0", "500", "1,000", "1,500", "2,000"])
    ax.set_ylabel("Altitude, feet MSL", color=TEXT_2, fontsize=18, labelpad=12)
    names = [s[0] for s in SKYLINE] + [
        "Hudson\nRiver",
        "E. River\nSouth",
        "E. River\nNorth",
        "Real NYC\nhelicopters",
    ]
    ax.set_xticks(SKY_X + CORR_X + [HELI_X])
    ax.set_xticklabels(names, fontsize=16, color=TEXT, linespacing=1.1)
    ax.tick_params(axis="x", length=0, pad=10)


def draw_right(ax: plt.Axes) -> None:
    style_axes(ax)
    for x0, x1, floor, ceil in PROTECTED_22:
        ax.add_patch(Rectangle((x0, floor), x1 - x0, ceil - floor, color=BLUE,
                               alpha=0.3, zorder=1))  # fmt: skip
    ys = [TDZE_FT, TDZE_FT + GLIDE_FT_PER_NM * 6.0]
    ax.plot([0.0, 6.0], ys, color=TEXT, linewidth=2.5, zorder=3)
    ax.text(5.9, 120, f"3° glidepath\n{GLIDE_FT_PER_NM:,.0f} ft per nm",
            ha="right", va="bottom", color=TEXT, fontsize=16, linespacing=1.1,
            zorder=5)  # fmt: skip
    ax.plot([MEDEVAC_NM], [MEDEVAC_FT], marker="o", markersize=18, color=CRITICAL,
            markeredgecolor=SURFACE, markeredgewidth=3, zorder=6)  # fmt: skip
    ax.annotate(
        "N312LM, simulated medevac\n600 ft at 1.1 nm, inside the\nfinal protected volume",
        xy=(MEDEVAC_NM, MEDEVAC_FT),
        xytext=(0.12, 1800),
        ha="left",
        va="center",
        color=TEXT,
        fontsize=16,
        linespacing=1.15,
        arrowprops={"arrowstyle": "-", "color": TEXT, "linewidth": 2},
        zorder=6,
    )
    ax.set_xlim(0, 6)
    ax.set_ylim(0, Y_MAX)
    ax.set_xticks(range(7))
    ax.set_yticks([0, 500, 1000, 1500, 2000])
    ax.tick_params(axis="y", labelleft=False)  # shared y-axis: don't clear the left labels
    ax.tick_params(axis="x", labelsize=17)
    ax.set_xlabel(
        "Distance from LGA Rwy 22 threshold, nautical miles",
        color=TEXT_2,
        fontsize=18,
        labelpad=10,
    )


def build(replay: Path, out_dir: Path) -> None:
    heli = load_helicopters(replay)
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none"})
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor=SURFACE)

    ax_l = fig.add_axes((0.075, 0.25, 0.52, 0.54))
    ax_r = fig.add_axes((0.665, 0.25, 0.29, 0.54), sharey=ax_l)
    draw_left(ax_l, heli)
    draw_right(ax_r)

    fig.text(
        0.075,
        0.955,
        "Helicopters, skyscrapers, and landing jets share the same ~2,000 feet",
        color=TEXT,
        fontsize=32,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.075,
        0.9,
        "Side view, feet MSL. Jet airliners typically cruise above 30,000 ft, "
        "far off this scale.",
        color=TEXT_2,
        fontsize=19,
        ha="left",
        va="center",
    )
    fig.text(
        0.075,
        0.845,
        "Skyscrapers, corridors, helicopters",
        color=TEXT,
        fontsize=21,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.665,
        0.845,
        "Airliners landing LGA Rwy 22",
        color=TEXT,
        fontsize=21,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.955,
        0.812,
        "Cruise above 30,000 ft: off scale",
        color=TEXT_2,
        fontsize=16,
        ha="right",
        va="center",
    )

    legend = [
        Patch(color=BUILDING, label="Skyscraper heights (CTBUH)"),
        Patch(color=BLUE, alpha=0.3, label="Hudson exclusion, to 1,300 ft"),
        Patch(color=ORANGE, alpha=0.3, label="East River exclusion"),
        Patch(color=AQUA, label="Real helicopters, 11:00 to 11:15 ET"),
        Patch(color=BLUE, alpha=0.3, label="LGA 22 protected final volume"),
        Patch(color=CRITICAL, label="Simulated medevac N312LM"),
    ]
    fig.legend(
        handles=legend,
        loc="lower left",
        bbox_to_anchor=(0.075, 0.1),
        ncol=3,
        frameon=False,
        fontsize=16,
        labelcolor=TEXT,
        handlelength=1.4,
        columnspacing=2.0,
    )

    fig.text(
        0.075,
        0.045,
        "DCA, Jan 29, 2025: an Army helicopter and an American Eagle CRJ "
        "collided on final. The Route 4 helicopter limit was 200 ft "
        "(NTSB, Mar 11, 2025).",
        color=TEXT,
        fontsize=17,
        ha="left",
        va="center",
    )
    fig.text(
        0.075,
        0.012,
        "Schematic, not to horizontal scale. Altitudes MSL. "
        "Simulation scenario. ADS-B: adsb.lol (ODbL).",
        color=TEXT_2,
        fontsize=15,
        ha="left",
        va="center",
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / "altitude_profile.png", dpi=100, facecolor=SURFACE)
    fig.savefig(out_dir / "altitude_profile.svg", facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, default=DEFAULT_REPLAY)
    parser.add_argument("--out", type=Path, default=FIG_DIR)
    args = parser.parse_args()
    build(args.replay, args.out)


if __name__ == "__main__":
    main()
