"""UKMTO warnings over 2026: cumulative share of posts by date, and cumulative markout (bps) summed across events.

Writes three outputs to analysis/output/databento/:
  ukmto_posts_cumulative_share.png  % of all UKMTO WARNING posts (data/ukmto_x_warnings_2026.csv) to each date
  ukmto_cumulative_bps_<h>.png      one chart per horizon (1m, 5m, 10m, 30m): running sum, in date order, of each warning's markout for CL, BZ and ES,
        from the per-event markout file written by hormuz_markouts.py. Warnings posted while Globex was closed
        have no markout and add nothing.
  ukmto_cumulative_bps_table.csv/.png  per asset (WTI, Brent, S&P 500): cumulative and average bps at
                                       1m / 5m / 10m / 30m

Usage:  python analysis/ukmto_cumulative.py [--horizons 1m,5m,10m,30m] [--tag ukmto_high+ukmto_medium+ukmto_low_all_noplacebo]
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hormuz_markouts import COLORS, OUT_DIR, ROOT  # noqa: E402

POSTS = ROOT / "data" / "ukmto_x_warnings_2026.csv"
EVENTS = ROOT / "data" / "ukmto_warning_events.csv"
KEEP = ["CL.v.0", "BZ.v.0", "ES.v.0"]
TABLE_HORIZONS = ["1m", "5m", "10m", "30m"]
INK, MUTED, GRID, BG = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
WAR_START = pd.Timestamp("2026-02-28", tz="UTC")


def style(ax):
    ax.set_facecolor(BG)
    ax.grid(axis="y", color=GRID, lw=0.6)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#c3c2b7")
    ax.tick_params(colors=MUTED)
    ax.axvline(WAR_START, color="#8a8984", lw=0.8, ls="--")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", default=",".join(TABLE_HORIZONS), help="comma list; one chart each")
    ap.add_argument("--tag", default="ukmto_high+ukmto_medium+ukmto_low_all_noplacebo")
    ap.add_argument("--start", default="2026-01-01")
    args = ap.parse_args()
    start = pd.Timestamp(args.start, tz="UTC")

    posts = pd.to_datetime(pd.read_csv(POSTS).datetime, utc=True).sort_values()
    posts = posts[posts >= start].reset_index(drop=True)
    end = posts.iloc[-1].normalize() + pd.Timedelta(days=1)
    share = pd.Series((posts.index + 1) / len(posts) * 100, index=pd.DatetimeIndex(posts))

    ev = pd.read_csv(OUT_DIR / f"markouts_by_event_{args.tag}.csv")
    times = pd.read_csv(EVENTS, parse_dates=["first_public_utc"]).set_index("event_id").first_public_utc
    ev["t"] = ev.event_id.map(times)
    ev = ev[ev.contract.isin(KEEP)].sort_values("t")
    names = {"CL.v.0": "WTI (CL)", "BZ.v.0": "Brent (BZ)", "ES.v.0": "S&P 500 (ES)"}

    # table: total of the per-warning markouts, Jan 1 to the last warning, for each horizon
    # table: one row per asset; cumulative (sum) and average (mean per warning) markout at each horizon
    rows = []
    for sym in KEEP:
        e = ev[ev.contract == sym]
        row = {"asset": names[sym], "n_warnings": int(e[TABLE_HORIZONS].notna().all(axis=1).sum())}
        row.update({f"cum_{h}": round(e[h].sum(), 1) for h in TABLE_HORIZONS})
        row.update({f"avg_{h}": round(e[h].mean(), 2) for h in TABLE_HORIZONS})
        rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(OUT_DIR / "ukmto_cumulative_bps_table.csv", index=False)
    print(table.to_string(index=False))
    save_table_png(table, OUT_DIR / "ukmto_cumulative_bps_table.png",
                   f"UKMTO Warnings: markout by asset (bps), 1 Jan to {end - pd.Timedelta(days=1):%d %b %Y}")

    note = ("Post times from X post IDs (PDF creation time where no archived post). Markout = change in quoted mid "
            "(Databento GLBX.MDP3 mbp-1) after each post; warnings outside Globex hours add 0.")

    # 1) cumulative share of posts
    fig, ax = plt.subplots(figsize=(13, 5.5), dpi=150)
    fig.patch.set_facecolor(BG)
    style(ax)
    ax.step([start, *share.index, end], [0, *share.values, 100], where="post", color=INK, lw=1.6)
    ax.set_ylim(0, 102)
    ax.set_ylabel("% of posts to date", color=MUTED)
    for q in (25, 50, 75):  # date each quartile of posts was reached
        d = share[share >= q].index[0]
        ax.annotate(f"{q}% by {d:%d %b}", (d, q), xytext=(6, -10), textcoords="offset points", fontsize=8,
                    color=MUTED)
        ax.plot(d, q, "o", ms=4, color=INK)
    ax.text(WAR_START, 98, " war begins 28 Feb", fontsize=8, color=MUTED, va="top")
    month_axis(ax, start, end)
    ax.set_title(f"UKMTO Warnings: cumulative share of posts in 2026 (n={len(posts)})", loc="left", fontsize=12,
                 color=INK)
    fig.text(0.01, 0.01, "Post times from X post IDs (PDF creation time where no archived post).", fontsize=7.5,
             color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out = OUT_DIR / "ukmto_posts_cumulative_share.png"
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(out)

    # 2) one cumulative-bps chart per horizon
    for h in args.horizons.split(","):
        e_h = ev.dropna(subset=[h])
        fig, az = plt.subplots(figsize=(13, 6.5), dpi=150)
        fig.patch.set_facecolor(BG)
        style(az)
        ends = []
        for sym in KEEP:
            e = e_h[e_h.contract == sym]
            cum = e[h].cumsum()
            az.step([start, *e.t, end], [0, *cum, cum.iloc[-1]], where="post", color=COLORS[sym], lw=1.6,
                    label=names[sym])
            ends.append([cum.iloc[-1], sym])
        # end labels, nudged apart so close totals stay legible
        ends.sort()
        span = np.diff(az.get_ylim())[0]
        y = [v for v, _ in ends]
        for k in range(1, len(y)):
            y[k] = max(y[k], y[k - 1] + 0.045 * span)
        for (v, sym), yk in zip(ends, y):
            az.text(end + pd.Timedelta(days=2), yk, f"{sym.split('.')[0]} {v:+.0f}", va="center", fontsize=9,
                    color=COLORS[sym], clip_on=False)
        az.axhline(0, color="#8a8984", lw=0.8)
        az.set_ylabel(f"Cumulative {h} markout (bps)", color=MUTED)
        az.legend(frameon=False, loc="upper left", fontsize=9)
        month_axis(az, start, end)
        az.set_title(f"UKMTO Warnings: cumulative {h} markout, 1 Jan to {end - pd.Timedelta(days=1):%d %b %Y} "
                     f"({e_h.event_id.nunique()} warnings during Globex hours)", loc="left", fontsize=12, color=INK)
        fig.text(0.01, 0.01, note, fontsize=7.5, color=MUTED)
        fig.tight_layout(rect=(0, 0.03, 0.97, 1))
        out = OUT_DIR / f"ukmto_cumulative_bps_{h}.png"
        fig.savefig(out, facecolor=fig.get_facecolor())
        plt.close(fig)
        print(out)

def save_table_png(table: pd.DataFrame, path: Path, title: str):
    fig, ax = plt.subplots(figsize=(12, 2.4), dpi=200)
    fig.patch.set_facecolor(BG)
    ax.axis("off")
    cum = [c for c in table.columns if c.startswith("cum_")]
    avg = [c for c in table.columns if c.startswith("avg_")]
    cells = [[r["asset"], *(f"{r[c]:+.1f}" for c in cum), *(f"{r[c]:+.2f}" for c in avg)]
             for _, r in table.iterrows()]
    cols = ["Asset", *(f"Cumulative\n{c[4:]}" for c in cum), *(f"Average\n{c[4:]}" for c in avg)]
    t = ax.table(cellText=cells, colLabels=cols, loc="center", cellLoc="right", colLoc="right")
    t.auto_set_font_size(False)
    t.set_fontsize(10)
    t.scale(1, 1.6)
    for (r, c), cell in t.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_facecolor(BG)
        cell.set_text_props(color=MUTED if r == 0 else INK, fontweight="bold" if r == 0 else "normal")
        if r == 0:
            cell.set_height(cell.get_height() * 1.8)  # two-line headers
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    fig.text(0.01, 0.03, "Cumulative = sum of each warning's markout at that horizon; average = mean per warning. "
             f"From the X post time; {table.n_warnings.max()} warnings posted during Globex hours.",
             fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(path)


def month_axis(ax, start, end):
    ax.set_xlim(start, end)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))

if __name__ == "__main__":
    main()
