"""Tick-level mid-price path for one event, from the mbp-1 cache written by hormuz_markouts.py.

Usage:  python analysis/event_path.py 2026-10-07_acers [--mark "20:03:00=AFP wire" ...]
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hormuz_markouts import CACHE_DIR, COLORS, CONTRACTS, EVENTS_CSV, HORIZONS, OUT_DIR, SCHEMA  # noqa: E402


def mid_paths(df: pd.DataFrame, t0: pd.Timestamp) -> dict:
    """contract -> Series of mid in bps vs mid(t0), indexed by seconds from t0."""
    out = {}
    for sym in CONTRACTS:
        q = df[(df.symbol == sym) & (df.bid_px_00 > 0) & (df.ask_px_00 > df.bid_px_00)].sort_values("ts_event")
        mid = (q.bid_px_00 + q.ask_px_00) / 2
        t = (q.ts_event - t0).dt.total_seconds()
        ref = mid[t <= 0].iloc[-1]
        out[sym] = pd.Series(((mid - ref) / ref * 1e4).values, index=t.values).groupby(level=0).last()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("event_id")
    ap.add_argument("--events", default=str(EVENTS_CSV))
    ap.add_argument("--mark", action="append", default=[], help='"HH:MM:SS=label", UTC on the event day')
    args = ap.parse_args()

    ev = pd.read_csv(args.events, parse_dates=["first_public_utc"]).set_index("event_id").loc[args.event_id]
    t0 = ev.first_public_utc
    df = pd.read_parquet(CACHE_DIR / f"{SCHEMA}_{t0.strftime('%Y%m%dT%H%M%S')}.parquet")
    paths = mid_paths(df, t0)
    marks = []
    for m in args.mark:
        hms, label = m.split("=", 1)
        marks.append(((pd.Timestamp(f"{t0.date()} {hms}", tz="UTC") - t0).total_seconds(), label))

    fig, (ax, az) = plt.subplots(2, 1, figsize=(12, 9), dpi=150, gridspec_kw={"height_ratios": [1.3, 1]})
    fig.patch.set_facecolor("#fcfcfb")
    windows = [(ax, -600, 3600, 60, "min", "Full markout window (−10 min to +1 h)"),
               (az, -60, 120, 1, "s", "Zoom: −60 s to +120 s around first public report")]
    for a, lo, hi, scale, unit, sub in windows:
        for sym, name in CONTRACTS.items():
            s = paths[sym]
            # carry the last quote before the window in, so the step line starts at the left edge
            pre = s[s.index < lo]
            s = s[(s.index >= lo) & (s.index <= hi)]
            if len(pre):
                s = pd.concat([pd.Series([pre.iloc[-1]], index=[lo]), s])
            a.step(s.index / scale, s.values, where="post", color=COLORS[sym], lw=1.3 if unit == "min" else 1.6,
                   label=name)
        for h, sec in HORIZONS.items():
            # sub-minute horizons crowd together on the minute-scale panel; label them only in the zoom
            if lo <= sec <= hi and sec != 0 and (unit == "s" or abs(sec) >= 300):
                a.axvline(sec / scale, color="#e6e5e0", lw=0.8, zorder=0)
                a.text(sec / scale, 1.0, h, transform=a.get_xaxis_transform(), ha="center", va="bottom",
                       fontsize=7, color="#8a8984")
        a.axvline(0, color="#0b0b0b", lw=1, ls="--")
        a.text(0, 0.98, f" UKMTO X post {t0.strftime('%H:%M:%S')}Z", transform=a.get_xaxis_transform(),
               va="top", fontsize=8, color="#0b0b0b")
        for sec, label in marks:
            if lo <= sec <= hi:
                a.axvline(sec / scale, color="#52514e", lw=0.9, ls=":")
                a.text(sec / scale, 0.90, f" {label}", transform=a.get_xaxis_transform(), va="top",
                       fontsize=8, color="#52514e")
        a.axhline(0, color="#8a8984", lw=0.8)
        a.set_xlim(lo / scale, hi / scale)
        a.set_facecolor("#fcfcfb")
        a.grid(axis="y", color="#e6e5e0", lw=0.6)
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            a.spines[sp].set_color("#c3c2b7")
        a.tick_params(colors="#52514e")
        a.set_ylabel("Mid vs mid at t0 (bps)", color="#52514e")
        a.set_xlabel(f"Time from first public report ({unit})", color="#52514e")
        a.set_title(sub, loc="left", fontsize=10, color="#52514e", pad=14)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.08), fontsize=9, ncol=len(CONTRACTS))
    fig.suptitle(f"{ev.event} — {t0.strftime('%a %d %b %Y')}, tick-by-tick quoted mid", x=0.01, ha="left",
                 fontsize=12, color="#0b0b0b")
    fig.text(0.01, 0.005, "Mid = (best bid + best ask)/2 from every top-of-book update (Databento GLBX.MDP3 mbp-1, "
             "ts_event). Step lines hold the last quote. Light gridlines = markout horizons.",
             fontsize=8, color="#52514e")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    out = OUT_DIR / f"event_path_{args.event_id}.png"
    fig.savefig(out, facecolor=fig.get_facecolor())
    print(out)
    for sym in CONTRACTS:
        s = paths[sym]
        print(sym, {h: round(float(s[s.index <= sec].iloc[-1]), 2) for h, sec in HORIZONS.items()})


if __name__ == "__main__":
    main()
