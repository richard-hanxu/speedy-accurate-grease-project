"""Brent and WTI daily spot since 2025, with the Brent–WTI spread and labelled events.

Data: EIA spot prices via FRED (free, no key). DCOILBRENTEU = Europe Brent spot FOB (physical Dated Brent),
DCOILWTICO = WTI Cushing spot. Cached in data/fred_<id>.csv; pass --refresh to re-download.

Usage:  python analysis/brent_wti_spread.py [--refresh] [--start 2025-01-01]
"""

import argparse
import textwrap
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_DIR = ROOT / "analysis" / "output" / "spread"
EVENTS_CSV = DATA / "brent_wti_spread_events.csv"
SERIES = {"brent": "DCOILBRENTEU", "wti": "DCOILWTICO"}
COLORS = {"brent": "#eb6834", "wti": "#2a78d6", "spread": "#0b0b0b"}
INK, MUTED, GRID, BG = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
# background regimes (from research/hormuz-timeline-2026-07-to-10.md)
REGIMES = [("2026-02-28", "2026-04-08", "War,\nHormuz shut"),
           ("2026-04-08", "2026-06-17", "Ceasefire +\nUS blockade"),
           ("2026-06-17", "2026-07-08", "MoU\ntruce"),
           ("2026-07-08", None, "Truce collapsed,\nblockade reinstated")]


def load(start: str, refresh: bool) -> pd.DataFrame:
    cols = {}
    for name, sid in SERIES.items():
        path = DATA / f"fred_{sid}.csv"
        if refresh or not path.exists():
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
            path.write_bytes(urllib.request.urlopen(url, timeout=30).read())
        cols[name] = pd.read_csv(path, index_col=0, parse_dates=True, na_values=".").iloc[:, 0]
    df = pd.DataFrame(cols).dropna()
    df = df[df.index >= start]
    df["spread"] = df.brent - df.wti
    return df


def style(ax):
    ax.set_facecolor(BG)
    ax.grid(axis="y", color=GRID, lw=0.6)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#c3c2b7")
    ax.tick_params(colors=MUTED)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--events", default=str(EVENTS_CSV))
    args = ap.parse_args()

    df = load(args.start, args.refresh)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.round(2).to_csv(OUT_DIR / "brent_wti_daily.csv", index_label="date")
    events = pd.read_csv(args.events, parse_dates=["date"]) if Path(args.events).exists() else pd.DataFrame()
    if len(events):
        events = events.sort_values("date").reset_index(drop=True)

    fig, (ax, az) = plt.subplots(2, 1, figsize=(15, 10.5), dpi=150, sharex=True,
                                 gridspec_kw={"height_ratios": [1.15, 1]})
    fig.patch.set_facecolor(BG)
    end = df.index[-1]

    for a in (ax, az):
        style(a)
        for i, (lo, hi, label) in enumerate(REGIMES):
            hi = pd.Timestamp(hi) if hi else end
            a.axvspan(pd.Timestamp(lo), hi, color="#f0efe9" if i % 2 == 0 else "#e9e8e1", zorder=0, lw=0)
            if a is ax:
                a.text(pd.Timestamp(lo) + (hi - pd.Timestamp(lo)) / 2, 1.0, label, transform=a.get_xaxis_transform(),
                       ha="center", va="bottom", fontsize=7.5, color=MUTED)

    for name in ("brent", "wti"):
        ax.plot(df.index, df[name], color=COLORS[name], lw=1.4, label="Brent (Dated, spot)" if name == "brent"
                else "WTI (Cushing, spot)")
        ax.annotate(f"{df[name].iloc[-1]:.0f}", (end, df[name].iloc[-1]), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=8, color=COLORS[name], annotation_clip=False)
    ax.set_ylabel("$/bbl", color=MUTED)
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    ax.set_title("Spot prices", loc="left", fontsize=10, color=MUTED, pad=16)

    s = df.spread
    base = s[s.index < "2026-02-28"].mean()
    az.fill_between(df.index, s, 0, where=s >= 0, color=COLORS["brent"], alpha=0.18, lw=0, interpolate=True)
    az.fill_between(df.index, s, 0, where=s < 0, color=COLORS["wti"], alpha=0.25, lw=0, interpolate=True)
    az.plot(df.index, s, color=COLORS["spread"], lw=1.1)
    az.axhline(0, color="#8a8984", lw=0.8)
    az.axhline(base, color=MUTED, lw=0.8, ls=":")
    az.text(df.index[0], base, f" pre-war avg ${base:.1f}", va="bottom", fontsize=7.5, color=MUTED)
    az.annotate(f"{s.iloc[-1]:.1f}", (end, s.iloc[-1]), xytext=(4, 0), textcoords="offset points", va="center",
                fontsize=8, color=INK, annotation_clip=False)
    az.set_ylabel("Brent − WTI ($/bbl)", color=MUTED)
    az.set_title("Brent − WTI spread (orange = Brent premium, blue = WTI above Brent); numbered events below",
                 loc="left", fontsize=10, color=MUTED)

    key = []
    for i, ev in events.iterrows():
        n = i + 1
        d = ev.date
        y = s.asof(d) if d >= s.index[0] else s.iloc[0]
        col = COLORS["brent"] if ev.direction == "widen" else COLORS["wti"]
        ls = "-" if ev.confidence == "confirmed" else "--"
        az.axvline(d, color=col, lw=0.6, ls=ls, alpha=0.6, zorder=1)
        ax.axvline(d, color=col, lw=0.6, ls=ls, alpha=0.35, zorder=1)
        az.plot(d, y, "o", ms=11, mfc="white", mec=col, mew=1.4, zorder=5)
        az.text(d, y, str(n), ha="center", va="center", fontsize=6.5, color=INK, zorder=6, fontweight="bold")
        key.append(f"{n:>2}. {d.strftime('%d %b %y')}  {ev.label}{'' if ev.confidence == 'confirmed' else ' (?)'}")

    az.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    az.xaxis.set_minor_locator(mdates.MonthLocator())
    az.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    az.set_xlim(pd.Timestamp(args.start), end)

    fig.suptitle(f"Brent vs WTI since {pd.Timestamp(args.start).strftime('%b %Y')}: when the spread widened and "
                 "contracted", x=0.01, ha="left", fontsize=13, color=INK)
    source = (f"Source: EIA via FRED (DCOILBRENTEU, DCOILWTICO), daily spot closes; last obs {end:%d %b %Y}.")
    bottom = 0.03
    if key:
        ncol = 3
        per = -(-len(key) // ncol)
        top = 0.012 + 0.0135 * per
        for c in range(ncol):
            fig.text(0.01 + c * 0.33, top, "\n".join(textwrap.shorten(k, 58) for k in key[c * per:(c + 1) * per]),
                     fontsize=8, color=INK, va="top", family="monospace", linespacing=1.35)
        fig.text(0.01, top + 0.012, "Events: orange = widened, blue = narrowed; dashed / (?) = plausible, not "
                 "confirmed (details in data/brent_wti_spread_events.csv).  " + source, fontsize=8, color=MUTED)
        bottom = top + 0.035
    else:
        fig.text(0.01, 0.005, source, fontsize=8, color=MUTED)
    fig.tight_layout(rect=(0, bottom, 1, 0.96))
    out = OUT_DIR / "brent_wti_spread.png"
    fig.savefig(out, facecolor=fig.get_facecolor())
    print(out)


if __name__ == "__main__":
    main()
