"""Does the market move BEFORE the UKMTO X post? Markouts from one minute before each "UKMTO WARNING" post.

Theory being tested: UKMTO publishes on its own site / to industry before X, so the price reaction may already be
under way when the X post appears. All markouts here are measured from the mid ONE MINUTE BEFORE the post:

    markout(h) = (mid(t0 + h) - mid(t0 - 1m)) / mid(t0 - 1m) * 1e4      h in -30s, -10s, -5s, -1s, 0s, 1s ... 1h

so the curve starts at 0 at -1m, and its value at 0s is the move that happened in the minute before the post.

Data: Databento mbp-1 (CL, BZ on CME; USO on NYSE Arca). The windows from ukmto_posts_markouts.py cover
[t0-60s, t0+60s] and the 60 s before +5m/10m/30m/1h; this adds [t0-120s, t0-60s] so the -1m quote has a lookback.
A horizon is blank when the market was closed at any point from t0-1m to t0+h, or no quote in the 60 s before it.

Outputs (analysis/output/ukmto_posts/warnings_only/pre_post/):
  pre_markouts_long.csv              one row per warning x asset x horizon (bid, ask, sizes, mid, bps)
  avg_from_minus1m_{full,since_aug}.png / _table.png    average curve, WTI / Brent / USO
  pre_vs_post_{full,since_aug}_table.png                 the minute before the post vs the minute after
  summary.csv

Usage:  python analysis/ukmto_pre_markouts.py [--cost-only]
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import databento as db
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hormuz_markouts import Client  # noqa: E402
from ukmto_posts_markouts import CACHE, COLS, FEEDS, OPEN, OUT, ckey, feed_args, path_open  # noqa: E402
from ukmto_warning_cumulative import ASSETS, BG, GRID, INK, MUTED, style  # noqa: E402

SRC = OUT / "warnings_only" / "markouts_long.csv"
DEST = OUT / "warnings_only" / "pre_post"
HZ = {"-1m": -60, "-30s": -30, "-10s": -10, "-5s": -5, "-1s": -1, "0s": 0, "1s": 1, "5s": 5, "10s": 10, "30s": 30,
      "1m": 60, "5m": 300, "10m": 600, "30m": 1800, "1h": 3600}
LOOKBACK = pd.Timedelta(seconds=60)
EPS = pd.Timedelta(milliseconds=1)
REFS = {"-1m": {}, "-10m": {"-10m": -600, "-5m": -300}}  # --ref: extra horizons before -1m
REF = "-1m"  # reference horizon; markouts are measured from the mid here
WORDS = {"-1m": "1 minute", "-10m": "10 minutes"}
PERIODS = {"full": ("2026-02-28", "28 Feb to 13 Nov 2026"), "since_aug": ("2026-08-01", "1 Aug to 13 Nov 2026")}


def tkey(t0):
    return f"{t0:%Y%m%dT%H%M%S%f}"


def feed_of(asset):
    return "GLBX" if asset in ("WTI", "Brent") else "USO"


def pre_path(feed, t0, s=-60):
    """Quotes for [t0+s-60s, t0+s] (s = -60 keeps the original file name)."""
    tag = "pre" if s == -60 else f"pre{-s}s"
    return CACHE / f"{tag}_{ckey(feed, FEEDS['USO'][0] if feed == 'USO' else 'GLBX.MDP3')}_{tkey(t0)}.parquet"


def fetch_pre(client: Client, feed: str, t0, s=-60) -> None:
    p = pre_path(feed, t0, s)
    if p.exists():
        return
    for attempt in range(5):
        try:
            data = client.get_range(schema="mbp-1", start=t0 + pd.Timedelta(seconds=s - 60),
                                    end=t0 + pd.Timedelta(seconds=s) + EPS, **feed_args(feed))
            break
        except db.BentoServerError:
            if attempt == 4:
                raise
            time.sleep(10 * (attempt + 1))
    df = data.to_df().reset_index()
    (df[COLS] if len(df) else pd.DataFrame(columns=COLS)).to_parquet(p)


def window_for(asset, t0, h):
    """Quotes covering the lookback before t0+h."""
    feed = feed_of(asset)
    prefix = ckey(feed, FEEDS[asset][0])
    if HZ[h] <= -120:
        parts = [pre_path(feed, t0, HZ[h])]
    elif h in ("5m", "10m", "30m", "1h"):
        parts = [CACHE / f"{prefix}_{tkey(t0)}_{h}.parquet"]
    else:
        parts = [pre_path(feed, t0), CACHE / f"{prefix}_{tkey(t0)}_near.parquet"]
    dfs = [pd.read_parquet(p) for p in parts if p.exists()]
    return pd.concat(dfs) if dfs else None


def quote_at(df, sym, t):
    q = df[(df.symbol == sym) & (df.bid_px_00 > 0) & (df.ask_px_00 > df.bid_px_00) & (df.ts_event <= t)
           & (df.ts_event > t - LOOKBACK - EPS)]
    return None if q.empty else q.sort_values("ts_event").iloc[-1]


def compute(posts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for p in posts.itertuples():
        for a in ASSETS:
            sym, t0 = FEEDS[a][2], p.t0_utc
            rs = HZ[REF]
            if not OPEN[a](t0 + pd.Timedelta(seconds=rs)):
                continue
            ref = None
            for h, s in HZ.items():
                rec = {"post_id": p.post_id, "t0_utc": t0, "asset": a, "horizon": h, "horizon_s": s}
                if path_open(OPEN[a], t0 + pd.Timedelta(seconds=rs), s - rs):
                    df = window_for(a, t0, h)
                    q = None if df is None else quote_at(df, sym, t0 + pd.Timedelta(seconds=s))
                    if q is not None:
                        mid = (q.bid_px_00 + q.ask_px_00) / 2
                        ref = mid if h == REF else ref
                        rec.update(bid=q.bid_px_00, ask=q.ask_px_00, bid_sz=q.bid_sz_00, ask_sz=q.ask_sz_00, mid=mid,
                                   markout_bps=(mid - ref) / ref * 1e4 if ref else np.nan)
                rows.append(rec)
    return pd.DataFrame(rows)


def chart(t, n, title, path):
    hz = list(HZ)
    fig, ax = plt.subplots(figsize=(13, 6.5), dpi=150)
    fig.patch.set_facecolor(BG)
    style(ax)
    xs = np.arange(len(hz))
    i0 = hz.index("0s")
    ax.axvspan(-0.5, i0, color="#efeee8", lw=0, zorder=0)
    ax.axvline(i0, color="#8a8984", lw=1, ls="--", zorder=1)
    ax.text(i0 - 0.1, 1, "before the X post", transform=ax.get_xaxis_transform(), ha="right", va="top", fontsize=9,
            color=MUTED)
    ax.text(i0 + 0.1, 1, "X post", transform=ax.get_xaxis_transform(), ha="left", va="top", fontsize=9, color=MUTED)
    for a, (label, col) in ASSETS.items():
        y = t.loc[a, hz].values.astype(float)
        ax.plot(xs, y, color=col, lw=2, marker="o", ms=6, mec=BG, mew=1.5, zorder=3,
                label=f"{label}  (n={int(n.loc[a, '0s'])})")
        ax.text(xs[-1] + 0.15, y[-1], f"{a} {y[-1]:+.2f}", va="center", fontsize=9, color=INK)
    ax.axhline(0, color="#8a8984", lw=0.8, zorder=1)
    ax.set_xticks(xs, hz)
    ax.set_xlim(-0.5, len(hz) - 1 + 1.0)
    ax.set_xlabel("Time relative to the X post (evenly spaced, not to scale)", color=MUTED)
    ax.set_ylabel(f"Average markout from mid at {REF} (bps)", color=MUTED)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0.0, 0.93), fontsize=9)
    ax.set_title(title, loc="left", fontsize=12, color=INK)
    fig.text(0.01, 0.01, 'Posts whose text contains "UKMTO WARNING"; post time from the X post ID. Markout = mid at the '
             f"horizon minus mid {WORDS[REF]} before the post (Databento: CME mbp-1 for CL/BZ, NYSE Arca for USO).\n"
             f"Warnings with the market closed at any point from {REF} to the horizon are excluded.", fontsize=7.5,
             color=MUTED)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def table_png(cells, cols, title, foot, path, width=19):
    fig, ax = plt.subplots(figsize=(width, 0.32 * len(cells) + 1.0), dpi=200)
    fig.patch.set_facecolor(BG)
    ax.axis("off")
    tb = ax.table(cellText=cells, colLabels=cols, loc="center", cellLoc="right", colLoc="right")
    tb.auto_set_font_size(False)
    tb.set_fontsize(10)
    tb.scale(1, 1.6)
    for (r, c), cell in tb.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_facecolor("#efeee8" if (r > 0 and cells[r - 1][0] == "") else BG)
        cell.set_text_props(color=MUTED if r == 0 else INK, fontweight="bold" if r == 0 else "normal")
        if r == 0 and any("\n" in c for c in cols):
            cell.set_height(cell.get_height() * 1.8)  # two-line headers
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    fig.text(0.01, 0.02, foot, fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-only", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--ref", choices=list(REFS), default="-1m", help="reference point; -10m adds -10m and -5m")
    args = ap.parse_args()
    global HZ, REF, DEST
    REF = args.ref
    HZ = {**REFS[REF], **HZ}
    if REF != "-1m":
        DEST = DEST.with_name(f"pre_post_from_minus{REF[1:]}")
    neg = [s for s in HZ.values() if s <= -60]

    m = pd.read_csv(SRC, dtype={"post_id": str})
    m["t0_utc"] = pd.to_datetime(m.t0_utc, utc=True)
    posts = m[["post_id", "t0_utc"]].drop_duplicates().sort_values("t0_utc")
    jobs = []
    for t0 in posts.t0_utc:
        for feed, assets in (("GLBX", ("WTI", "Brent")), ("USO", ("USO",))):
            for s in neg:
                if any(OPEN[a](t0 + pd.Timedelta(seconds=s)) for a in assets) and not pre_path(feed, t0, s).exists():
                    jobs.append((feed, t0, s))
    client = Client()
    if args.cost_only:
        c = sum(client.metadata.get_cost(schema="mbp-1", start=t0 + pd.Timedelta(seconds=s - 60),
                                         end=t0 + pd.Timedelta(seconds=s), **feed_args(f)) for f, t0, s in jobs[:30])
        print(f"{len(jobs)} pre-post windows, est ${c / max(1, min(30, len(jobs))) * len(jobs):.2f}")
        return
    with ThreadPoolExecutor(args.workers) as ex:
        list(ex.map(lambda j: fetch_pre(client, *j), jobs))

    d = compute(posts)
    DEST.mkdir(parents=True, exist_ok=True)
    d.to_csv(DEST / "pre_markouts_long.csv", index=False)
    hz = list(HZ)
    MIRROR = REF[1:]  # the same length of time after the post
    summ = []
    for per, (start, plabel) in PERIODS.items():
        x = d[d.t0_utc >= pd.Timestamp(start, tz="UTC")].dropna(subset=["markout_bps"])
        g = x.groupby(["asset", "horizon"]).markout_bps
        t, n = g.mean().unstack()[hz], g.count().unstack()[hz]
        stem = f"avg_from_minus{REF[1:]}_{per}"
        chart(t, n, f"UKMTO Warnings: average mid-to-mid markout from {WORDS[REF]} before the X post, {plabel}",
              DEST / f"{stem}.png")
        cells = []
        for a, (label, _) in ASSETS.items():
            cells.append([label, *(f"{v:+.2f}" for v in t.loc[a, hz])])
            cells.append(["", *(f"n={int(v)}" for v in n.loc[a, hz])])
        table_png(cells, ["Asset (bps)", *hz], f"UKMTO Warnings: average markout from mid at {REF} (bps), {plabel}",
                  f"Mid-to-mid, measured from the mid {WORDS[REF]} before the X post; shaded rows = number of warnings.",
                  DEST / f"{stem}_table.png", width=19 + 2.5 * (len(hz) - 15))

        # the minute before the post vs the minute after: direction and size of moves
        w = x.pivot_table(index=["post_id", "asset"], columns="horizon", values="mid")
        rows = []
        for a, (label, _) in ASSETS.items():
            ww = w.xs(a, level="asset").dropna(subset=[REF, "0s", MIRROR])
            pre = (ww["0s"] - ww[REF]) / ww[REF] * 1e4
            post = (ww[MIRROR] - ww["0s"]) / ww["0s"] * 1e4
            rows.append({"period": per, "asset": label, "n": len(ww),
                         "pre_mean": pre.mean(), "pre_mean_abs": pre.abs().mean(), "pre_up_pct": (pre > 0).mean() * 100,
                         "pre_gt10_pct": (pre.abs() > 10).mean() * 100,
                         "post_mean": post.mean(), "post_mean_abs": post.abs().mean(),
                         "post_up_pct": (post > 0).mean() * 100, "post_gt10_pct": (post.abs() > 10).mean() * 100})
        r = pd.DataFrame(rows)
        summ.append(r)
        cells = [[q.asset, f"{q.n}", f"{q.pre_mean:+.2f}", f"{q.pre_mean_abs:.2f}", f"{q.pre_up_pct:.0f}%",
                  f"{q.pre_gt10_pct:.0f}%", f"{q.post_mean:+.2f}", f"{q.post_mean_abs:.2f}", f"{q.post_up_pct:.0f}%",
                  f"{q.post_gt10_pct:.0f}%"] for q in r.itertuples()]
        b, f_ = f"{REF}→0", f"0→+{MIRROR}"
        table_png(cells, ["Asset", "Warnings", f"{b}\navg bps", f"{b}\navg |bps|", f"{b}\n% up", f"{b}\n% |move|>10",
                          f"{f_}\navg bps", f"{f_}\navg |bps|", f"{f_}\n% up", f"{f_}\n% |move|>10"],
                  f"UKMTO Warnings: the {WORDS[REF]} before the X post vs the {WORDS[REF]} after, {plabel}",
                  f"If the market reacted before the X post, the {WORDS[REF]} before should show larger and mostly "
                  f"upward moves than the {WORDS[REF]} after.", DEST / f"pre_vs_post_{per}_table.png", width=15)
    s = pd.concat(summ).round(2)
    s.to_csv(DEST / "summary.csv", index=False)
    with pd.option_context("display.width", 220):
        for per, (start, _) in PERIODS.items():
            x = d[d.t0_utc >= pd.Timestamp(start, tz="UTC")].dropna(subset=["markout_bps"])
            print(f"\n{per}")
            print(x.groupby(["asset", "horizon"]).markout_bps.mean().unstack()[hz].round(2).to_string())
            print(x.groupby(["asset", "horizon"]).markout_bps.count().unstack()[hz].to_string())
        print(s.to_string(index=False))
    print(DEST)


if __name__ == "__main__":
    main()
