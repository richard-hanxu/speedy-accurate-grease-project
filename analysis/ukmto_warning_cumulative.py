"""Cumulative mid-to-mid markout (bps) after each "UKMTO WARNING" post since 28 Feb 2026, one chart per horizon,
WTI (CL), Brent (BZ) and USO on the same chart; plus a table PNG per horizon with trades, win rate, totals.

Input: analysis/output/ukmto_posts/warnings_only/markouts_long.csv (from ukmto_warning_markouts.py).
A "trade" is one warning with a markout at that horizon (market open from the post to the horizon).
Win = mid higher at the horizon than at the post; unchanged mid counts as not a win.

Outputs (analysis/output/ukmto_posts/warnings_only/cumulative/):
  cumulative_bps_<h>.png, table_<h>.png, cumulative_table.csv
"""

import argparse
import textwrap
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ukmto_posts_markouts import OUT  # noqa: E402

SRC = OUT / "warnings_only" / "markouts_long.csv"
DEST = OUT / "warnings_only" / "cumulative"
HORIZONS = ["1m", "5m", "10m", "30m", "1h"]
ASSETS = {"WTI": ("WTI (CL)", "#2a78d6"), "Brent": ("Brent (BZ)", "#eb6834"), "USO": ("USO", "#1baf7a")}
INK, MUTED, GRID, BG = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
START, END = pd.Timestamp("2026-02-28", tz="UTC"), pd.Timestamp("2026-11-14", tz="UTC")  # START set by --start
PERIOD = "28 Feb to 13 Nov 2026"
# what the markout measures; replaced by analysis/ukmto_entry_rules.py for its entry rules
LABEL = "mid-to-mid markout"
NOTE = ("Markout = change in quoted mid (Databento: CME mbp-1 for CL/BZ, NYSE Arca for USO).")
WIN = "mid higher at +{h} than at the post"


def style(ax):
    ax.set_facecolor(BG)
    ax.grid(axis="y", color=GRID, lw=0.6)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#c3c2b7")
    ax.tick_params(colors=MUTED)


def chart(m: pd.DataFrame, h: str):
    fig, ax = plt.subplots(figsize=(13, 6.5), dpi=150)
    fig.patch.set_facecolor(BG)
    style(ax)
    ends = []
    for a, (label, col) in ASSETS.items():
        e = m[(m.asset == a) & (m.horizon == h)].dropna(subset=["markout_bps"]).sort_values("t0_utc")
        cum = e.markout_bps.cumsum()
        ax.step([START, *e.t0_utc, END], [0, *cum, cum.iloc[-1]], where="post", color=col, lw=2,
                label=f"{label}  (n={len(e)})")
        ends.append([cum.iloc[-1], a])
    ax.axhline(0, color="#8a8984", lw=0.8)
    # end labels in text ink, nudged apart; the colored line beside them carries identity
    ends.sort()
    span = np.diff(ax.get_ylim())[0]
    ys = [v for v, _ in ends]
    for k in range(1, len(ys)):
        ys[k] = max(ys[k], ys[k - 1] + 0.05 * span)
    for (v, a), y in zip(ends, ys):
        ax.text(END + pd.Timedelta(days=2), y, f"{a} {v:+.0f}", va="center", fontsize=9, color=INK, clip_on=False)
    ax.set_xlim(START, END)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.set_ylabel(f"Cumulative {h} markout (bps)", color=MUTED)
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    ax.set_title(f"UKMTO Warnings: cumulative {h} {LABEL}, {PERIOD}", loc="left",
                 fontsize=12, color=INK)
    foot = textwrap.fill('Posts whose text contains "UKMTO WARNING"; time from the X post ID. ' + NOTE +
                         " Posts while the market was closed are excluded.", 210)
    fig.text(0.01, 0.01, foot, fontsize=7.5, color=MUTED, va="bottom")
    fig.tight_layout(rect=(0, 0.02 + 0.018 * foot.count("\n") + 0.012, 0.96, 1))
    fig.savefig(DEST / f"cumulative_bps_{h}.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def table_png(t: pd.DataFrame, h: str):
    fig, ax = plt.subplots(figsize=(14.5, 2.2), dpi=200)
    fig.patch.set_facecolor(BG)
    ax.axis("off")
    cols = ["Asset", "Executed\ntrades", "Wins", "Win rate", "Win rate\nex. unchanged", "Cumulative\n(bps)",
            "Average\n(bps)", "Cumulative\n(spreads)", "Average\n(spreads)", "Avg quoted\nspread (\\$)"]
    cells = [[r.asset, f"{r.trades}", f"{r.wins}", f"{r.win_rate_pct:.1f}%", f"{r.win_rate_ex_flat_pct:.1f}%",
              f"{r.cum_bps:+.1f}", f"{r.avg_bps:+.2f}", f"{r.cum_spreads:+.1f}",
              f"{r.avg_spreads:+.2f}", f"{r.avg_quoted_spread_px:.3f}"] for r in t.itertuples()]
    tb = ax.table(cellText=cells, colLabels=cols, loc="center", cellLoc="right", colLoc="right")
    tb.auto_set_font_size(False)
    tb.set_fontsize(10)
    tb.scale(1, 1.6)
    for (r, c), cell in tb.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_facecolor(BG)
        cell.set_text_props(color=MUTED if r == 0 else INK, fontweight="bold" if r == 0 else "normal")
        if r == 0:
            cell.set_height(cell.get_height() * 1.8)
    ax.set_title(f"UKMTO Warnings: {h} {LABEL} by asset, {PERIOD}", loc="left", fontsize=11, color=INK)
    fig.text(0.01, 0.03, "Trade = one warning with a quote at the post and at +" + h + "; win = " + WIN.format(h=h) +
             ". Spreads = P&L (\\$) / average quoted spread (\\$). Total trades across assets: " + f"{t.trades.sum()}.",
             fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(DEST / f"table_{h}.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    global START, PERIOD, DEST
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="first post date, e.g. 2026-08-01; outputs go to cumulative_since_<date>/")
    args = ap.parse_args()
    m = pd.read_csv(SRC)
    m["t0_utc"] = pd.to_datetime(m.t0_utc, utc=True)
    if args.start:
        START = pd.Timestamp(args.start, tz="UTC")
        m = m[m.t0_utc >= START]
        PERIOD = f"{START:%-d %b} to 13 Nov 2026"
        DEST = DEST.with_name(f"cumulative_since_{START:%Y%m%d}")
    run(m, HORIZONS)


def run(m: pd.DataFrame, horizons) -> pd.DataFrame:
    """m: long rows with asset, horizon, t0_utc, markout_bps, markout_spreads, and spread_px on the 0s rows."""
    DEST.mkdir(parents=True, exist_ok=True)
    rows = []
    for h in horizons:
        chart(m, h)
        t = []
        for a, (label, _) in ASSETS.items():
            e = m[(m.asset == a) & (m.horizon == h)].dropna(subset=["markout_bps"])
            x = e.markout_bps
            z = m[(m.asset == a) & (m.horizon == "0s")]
            q0 = (z if len(z) else e).spread_px.mean()  # quoted spread at the post
            up, down = int((x > 0).sum()), int((x < 0).sum())
            t.append({"horizon": h, "asset": label, "trades": len(x), "wins": up, "losses": down,
                      "unchanged": len(x) - up - down, "win_rate_pct": up / len(x) * 100,
                      "win_rate_ex_flat_pct": up / (up + down) * 100, "cum_bps": x.sum(), "avg_bps": x.mean(),
                      "cum_spreads": e.markout_spreads.sum(), "avg_spreads": e.markout_spreads.mean(),
                      "avg_quoted_spread_px": q0})
        t = pd.DataFrame(t)
        table_png(t, h)
        rows.append(t)
    out = pd.concat(rows).round(2)
    out.to_csv(DEST / "cumulative_table.csv", index=False)
    print(out.to_string(index=False))
    print(DEST)
    return out


if __name__ == "__main__":
    main()
