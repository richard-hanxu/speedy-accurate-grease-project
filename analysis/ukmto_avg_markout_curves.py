"""Average markout curve after "UKMTO WARNING" posts, by horizon (1s .. 1h), for WTI (CL), Brent (BZ) and USO.

8 charts = 2 measures x 2 units x 2 periods, each with a table PNG of the plotted values:
  measure  mid_to_mid      (mid(t0+h) - mid(t0))
           passive_to_mid  (mid(t0+h) - bid(t0))   long filled at the best bid at the post (assumed always filled)
  unit     bps             / entry price * 1e4
           spreads         / the asset's average quoted spread in dollars (as in ukmto_posts_markouts.py)
  period   full            28 Feb - 13 Nov 2026
           since_aug       1 Aug - 13 Nov 2026

Input: analysis/output/ukmto_posts/warnings_only/markouts_long.csv.
Outputs: analysis/output/ukmto_posts/warnings_only/avg_curves/<measure>_<unit>_<period>.png / _table.png,
         avg_curves.csv (all values, with n).
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ukmto_warning_cumulative import ASSETS, BG, GRID, INK, MUTED, style  # noqa: E402
from ukmto_posts_markouts import OUT  # noqa: E402

SRC = OUT / "warnings_only" / "markouts_long.csv"
DEST = OUT / "warnings_only" / "avg_curves"
HZ = ["1s", "5s", "10s", "30s", "1m", "5m", "10m", "30m", "1h"]
MEASURES = {"mid_to_mid": "mid to mid", "passive_to_mid": "passive (bid at post) to mid"}
UNITS = {"bps": "bps", "spreads": "average spreads"}
PERIODS = {"full": ("2026-02-28", "28 Feb to 13 Nov 2026"), "since_aug": ("2026-08-01", "1 Aug to 13 Nov 2026")}


def build(m: pd.DataFrame) -> pd.DataFrame:
    z = m[m.horizon == "0s"].set_index(["t0_utc", "asset"])[["bid", "mid", "avg_spread_px"]]
    x = m[m.horizon.isin(HZ)].dropna(subset=["mid"]).join(z, on=["t0_utc", "asset"], rsuffix="0")  # noqa
    x = x.dropna(subset=["mid0", "bid0"])
    out = []
    for meas, ref in (("mid_to_mid", "mid0"), ("passive_to_mid", "bid0")):
        pnl = x.mid - x[ref]
        out.append(x.assign(measure=meas, bps=pnl / x[ref] * 1e4, spreads=pnl / x.avg_spread_px0))
    return pd.concat(out)


def chart(t: pd.DataFrame, n: pd.DataFrame, title: str, unit: str, path: Path):
    fig, ax = plt.subplots(figsize=(11, 6), dpi=150)
    fig.patch.set_facecolor(BG)
    style(ax)
    xs = np.arange(len(HZ))
    for a, (label, col) in ASSETS.items():
        y = t.loc[a, HZ].values.astype(float)
        ax.plot(xs, y, color=col, lw=2, marker="o", ms=6, mec=BG, mew=1.5,
                label=f"{label}  (n={int(n.loc[a, '1m'])})", zorder=3)
        ax.text(xs[-1] + 0.15, y[-1], f"{a} {y[-1]:+.2f}", va="center", fontsize=9, color=INK)
    ax.axhline(0, color="#8a8984", lw=0.8, zorder=1)
    ax.set_xticks(xs, HZ)
    ax.set_xlim(-0.3, len(HZ) - 1 + 0.9)
    ax.set_xlabel("Time after the post", color=MUTED)
    ax.set_ylabel(f"Average markout ({UNITS[unit]})", color=MUTED)
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    ax.set_title(title, loc="left", fontsize=12, color=INK)
    fig.text(0.01, 0.01, 'Posts whose text contains "UKMTO WARNING"; time from the X post ID. Horizons are evenly '
             "spaced, not to scale.\nSpreads = P&L (\\$) / average quoted spread (\\$). Posts while the market was closed "
             "are excluded.", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def table_png(t: pd.DataFrame, n: pd.DataFrame, title: str, unit: str, path: Path):
    fmt = "{:+.2f}" if unit == "bps" else "{:+.3f}"
    fig, ax = plt.subplots(figsize=(13, 1.9), dpi=200)
    fig.patch.set_facecolor(BG)
    ax.axis("off")
    cells = [[ASSETS[a][0], f"{int(n.loc[a, '1s'])}-{int(n.loc[a, '1h'])}", *(fmt.format(v) for v in t.loc[a, HZ])]
             for a in ASSETS]
    tb = ax.table(cellText=cells, colLabels=["Asset", "n", *HZ], loc="center", cellLoc="right", colLoc="right")
    tb.auto_set_font_size(False)
    tb.set_fontsize(10)
    tb.scale(1, 1.6)
    for (r, c), cell in tb.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_facecolor(BG)
        cell.set_text_props(color=MUTED if r == 0 else INK, fontweight="bold" if r == 0 else "normal")
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    fig.text(0.01, 0.03, f"Average markout in {UNITS[unit]}; n = warnings with a quote at the post and at the horizon "
             "(1s to 1h).", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    m = pd.read_csv(SRC)
    m["t0_utc"] = pd.to_datetime(m.t0_utc, utc=True)
    d = build(m)
    DEST.mkdir(parents=True, exist_ok=True)
    rows = []
    for per, (start, plabel) in PERIODS.items():
        dp = d[d.t0_utc >= pd.Timestamp(start, tz="UTC")]
        for meas, mlabel in MEASURES.items():
            dm = dp[dp.measure == meas]
            n = dm.groupby(["asset", "horizon"]).bps.count().unstack()
            for unit in UNITS:
                t = dm.groupby(["asset", "horizon"])[unit].mean().unstack()
                title = f"UKMTO Warnings: average markout, {mlabel}, {UNITS[unit]}, {plabel}"
                stem = f"{meas}_{unit}_{per}"
                chart(t, n, title, unit, DEST / f"{stem}.png")
                table_png(t, n, title, unit, DEST / f"{stem}_table.png")
                for a in ASSETS:
                    for h in HZ:
                        rows.append({"period": per, "measure": meas, "unit": unit, "asset": a, "horizon": h,
                                     "mean": t.loc[a, h], "n": int(n.loc[a, h])})
    out = pd.DataFrame(rows)
    out.to_csv(DEST / "avg_curves.csv", index=False)
    with pd.option_context("display.width", 200):
        for (per, meas, unit), g in out.groupby(["period", "measure", "unit"], sort=False):
            print(f"\n{per} | {meas} | {unit}")
            print(g.pivot(index="asset", columns="horizon", values="mean")[HZ].loc[list(ASSETS)]
                  .round(3 if unit == "spreads" else 2).to_string())
    print(DEST)


if __name__ == "__main__":
    main()
