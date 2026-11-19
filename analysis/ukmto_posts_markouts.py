"""Markouts of WTI (CL), Brent (BZ) futures and the USO ETF after every @UK_MTO post since the war began.

Posts: browser/ukmto_x_posts.json (scraped X timeline; timestamp_utc decoded from the post ID, ms precision).
Only posts at or after 2026-02-28 (start of the Strait of Hormuz conflict) are used.

Market data (Databento, mbp-1 = every top-of-book change, with sizes):
  CL.v.0, BZ.v.0   GLBX.MDP3, volume-leading continuous contract
  USO              ARCX.PILLAR (NYSE Arca, the primary listing; EQUS.MINI was tried first but its USO quotes
                   carry stub/stale prices, e.g. a $0.93 bid against a $104 ask)
To keep cost down, only short windows are downloaded per post: [t0-60s, t0+60s] (covers 0s..1m) and the
60 s before each of t0+5m, 10m, 30m, 1h. The quote at a horizon is the last top-of-book update at or before it.

Markout(h) = (mid(t0+h) - mid(t0)) / mid(t0) * 1e4  (bps).  Also expressed in average spreads:
mid change in $ / average quoted spread in $ (ask - bid), the average being taken from Databento's bbo-1m schema (the
best bid/offer sampled once a minute) over the whole period, during the asset's trading hours. One record per
minute instead of every tick.

A horizon is blank when the market was closed at t0 or at any point up to t0+h, or no quote arrived in the
60 s before it.

Outputs (analysis/output/ukmto_posts/):
  markouts_long.csv        one row per post x asset x horizon: bid, ask, bid_sz, ask_sz, mid, spread_px, spread_bps, markout_px,
                           markout_bps, markout_spreads
  markouts_wide_bps.csv    one row per post x asset, horizons as columns
  avg_spread.csv           average spread per asset (bbo-1m)
  summary.csv              mean / median / n per asset x horizon x post group (all, warnings)

Usage:  python analysis/ukmto_posts_markouts.py [--cost-only] [--workers 8]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import databento as db
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hormuz_markouts import Client, globex_open  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "browser" / "ukmto_x_posts.json"
OUT = ROOT / "analysis" / "output" / "ukmto_posts"
CACHE = Path(os.environ.get("MARKOUT_CACHE", Path.home() / ".cache" / "speedy-grease" / "cache")) / "ukmto_posts"
WAR_START = pd.Timestamp("2026-02-28", tz="UTC")
HORIZONS = {"0s": 0, "1s": 1, "5s": 5, "10s": 10, "30s": 30, "1m": 60, "5m": 300, "10m": 600, "30m": 1800,
            "1h": 3600}
LOOKBACK = pd.Timedelta(seconds=60)
EPS = pd.Timedelta(milliseconds=1)
FEEDS = {  # name -> (dataset, stype_in, symbol)
    "WTI": ("GLBX.MDP3", "continuous", "CL.v.0"),
    "Brent": ("GLBX.MDP3", "continuous", "BZ.v.0"),
    "USO": ("ARCX.PILLAR", "raw_symbol", "USO"),
}
COLS = ["ts_event", "symbol", "bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00"]


# --- posts ------------------------------------------------------------------------------------------------
def post_type(head: str) -> str:
    h = head.upper()
    if "WARNING" in h:
        return "warning"
    if "ADVISORY" in h and "JMIC" not in h:
        return "advisory"
    if "JMIC" in h:
        return "jmic"
    if "DAILY SUMMARY" in h or "DAILY_SUMMARY" in h:
        return "daily_summary"
    if "OVERVIEW" in h:
        return "overview"
    return "other"


def load_posts() -> pd.DataFrame:
    d = pd.DataFrame(json.load(open(POSTS)))
    d["t0"] = pd.to_datetime(d.timestamp_utc, utc=True)
    # text = "UKMTO Operations Centre / @UK_MTO / · / <age> / <first line of post> ..."
    d["headline"] = d.text.str.split("\n").map(lambda ls: next((x.strip() for x in ls[4:] if x.strip()), ""))
    d["post_type"] = d.headline.map(post_type)
    d = d[d.t0 >= WAR_START].drop_duplicates("id").sort_values("t0").reset_index(drop=True)
    return d[["id", "t0", "post_type", "headline", "url"]]


# --- sessions -----------------------------------------------------------------------------------------------
def uso_open(ts: pd.Timestamp) -> bool:
    """US equities incl. extended hours, 04:00-20:00 ET Mon-Fri (holidays show up as missing quotes)."""
    et = ts.tz_convert("America/New_York")
    return et.weekday() < 5 and 4 <= et.hour + et.minute / 60 < 20


def uso_session(ts: pd.Timestamp) -> str:
    et = ts.tz_convert("America/New_York")
    hm = et.hour + et.minute / 60
    if not uso_open(ts):
        return "closed"
    return "regular" if 9.5 <= hm < 16 else "extended"


def path_open(is_open, t0: pd.Timestamp, s: float) -> bool:
    grid = pd.date_range(t0, t0 + pd.Timedelta(seconds=s), freq="1min").append(
        pd.DatetimeIndex([t0 + pd.Timedelta(seconds=s)]))
    return all(is_open(g) for g in grid)


OPEN = {"WTI": globex_open, "Brent": globex_open, "USO": uso_open}


# --- windows ------------------------------------------------------------------------------------------------
def windows(t0: pd.Timestamp) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    w = [("near", t0 - LOOKBACK, t0 + pd.Timedelta(seconds=60) + EPS)]
    for h in ("5m", "10m", "30m", "1h"):
        t = t0 + pd.Timedelta(seconds=HORIZONS[h])
        w.append((h, t - LOOKBACK, t + EPS))
    return w


def jobs(posts: pd.DataFrame):
    """(feed, dataset, key, start, end) for every window whose market is open at t0."""
    out = []
    for p in posts.itertuples():
        for name, (dataset, _, _) in FEEDS.items():
            if not OPEN[name](p.t0):
                continue
            # GLBX feeds share one request (both symbols)
            feed = "GLBX" if dataset == "GLBX.MDP3" else name
            for tag, s, e in windows(p.t0):
                if tag != "near" and not path_open(OPEN[name], p.t0, HORIZONS[tag]):
                    continue
                out.append((feed, dataset, f"{ckey(feed, dataset)}_{p.t0:%Y%m%dT%H%M%S%f}_{tag}", s, e))
    return list(dict.fromkeys(out))


def ckey(feed: str, dataset: str) -> str:
    """cache-key prefix; USO carries its dataset so a change of venue never reuses old windows"""
    return feed if feed == "GLBX" else f"{feed}-{dataset}"


def feed_args(feed: str) -> dict:
    if feed == "GLBX":
        return dict(dataset="GLBX.MDP3", stype_in="continuous", symbols=["CL.v.0", "BZ.v.0"])
    ds, st, sym = FEEDS[feed]
    return dict(dataset=ds, stype_in=st, symbols=[sym])


def fetch(client: Client, job) -> pd.DataFrame:
    feed, _, key, s, e = job
    path = CACHE / f"{key}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    for attempt in range(5):
        try:
            data = client.get_range(schema="mbp-1", start=s, end=e, **feed_args(feed))
            break
        except db.BentoServerError:
            if attempt == 4:
                raise
            time.sleep(10 * (attempt + 1))
    df = data.to_df().reset_index()
    df = df[COLS] if len(df) else pd.DataFrame(columns=COLS)
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


def estimate_cost(client: Client, js) -> float:
    """Exact cost of a random sample of windows, scaled up (one cost call per window would be slow)."""
    rng = np.random.default_rng(0)
    total = 0.0
    for feed in sorted({j[0] for j in js}):
        fj = [j for j in js if j[0] == feed and not (CACHE / f"{j[2]}.parquet").exists()]
        if not fj:
            continue
        sample = [fj[i] for i in rng.choice(len(fj), min(30, len(fj)), replace=False)]
        c = sum(client.metadata.get_cost(schema="mbp-1", start=s, end=e, **feed_args(f)) for f, _, _, s, e in sample)
        est = c / len(sample) * len(fj)
        print(f"  {feed}: {len(fj)} windows, sample of {len(sample)} costs ${c:.4f} -> est ${est:.2f}")
        total += est
    return total


# --- average spread from bbo-1m ---------------------------------------------------------------------------
def avg_spread(client: Client, start: pd.Timestamp, end: pd.Timestamp, cost_only: bool) -> pd.DataFrame | float:
    reqs = {"GLBX": feed_args("GLBX")}  # USO: see uso_window_spread
    if cost_only:
        return sum(client.metadata.get_cost(schema="bbo-1m", start=start, end=end, **a) for a in reqs.values())
    rows = []
    for feed, a in reqs.items():
        path = CACHE / f"bbo1m_{feed}_{start:%Y%m%d}_{end:%Y%m%d}.parquet"
        if path.exists():
            df = pd.read_parquet(path)
        else:
            df = client.get_range(schema="bbo-1m", start=start, end=end, **a).to_df().reset_index()
            df = df[["ts_recv", "symbol", "bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00"]]
            CACHE.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path)
        df = df[(df.bid_px_00 > 0) & (df.ask_px_00 > df.bid_px_00)].copy()
        df["mid"] = (df.bid_px_00 + df.ask_px_00) / 2
        df["spread_bps"] = (df.ask_px_00 - df.bid_px_00) / df.mid * 1e4
        df["spread_px"] = df.ask_px_00 - df.bid_px_00
        et = df.ts_recv.dt.tz_convert("America/New_York")
        hm = et.dt.hour + et.dt.minute / 60
        for sym, g in df.groupby("symbol"):
            name = {"CL.v.0": "WTI", "BZ.v.0": "Brent", "USO": "USO"}[sym]
            if name == "USO":
                sel = {"regular": (hm >= 9.5) & (hm < 16), "extended": ((hm >= 4) & (hm < 9.5)) | ((hm >= 16) & (hm < 20))}
            else:
                sel = {"all": pd.Series(True, index=df.index)}
            for sess, m in sel.items():
                x = g[m.loc[g.index]]
                rows.append({"asset": name, "session": sess, "n_minutes": len(x),
                             "mean_spread_bps": x.spread_bps.mean(), "median_spread_bps": x.spread_bps.median(),
                             "mean_spread_px": x.spread_px.mean(), "mean_bid_sz": x.bid_sz_00.mean(),
                             "mean_ask_sz": x.ask_sz_00.mean()})
    return pd.DataFrame(rows)


def uso_window_spread(posts: pd.DataFrame, data: dict) -> pd.DataFrame:
    rows = {"regular": [], "extended": []}
    for p in posts.itertuples():
        df = data.get(f"{ckey('USO', FEEDS['USO'][0])}_{p.t0:%Y%m%dT%H%M%S%f}_near")
        sess = uso_session(p.t0)
        if df is None or sess == "closed":
            continue
        q = df[(df.bid_px_00 > 0) & (df.ask_px_00 > df.bid_px_00) & (df.ts_event < p.t0)].sort_values("ts_event")
        if len(q) < 2:
            continue
        dur = np.diff(np.append(q.ts_event.values.astype("int64"), p.t0.value))  # ns each quote was live
        mid = (q.bid_px_00 + q.ask_px_00) / 2
        bps = ((q.ask_px_00 - q.bid_px_00) / mid * 1e4).values
        rows[sess].append((np.average(bps, weights=dur), np.average(q.ask_px_00 - q.bid_px_00, weights=dur),
                           np.average(q.bid_sz_00, weights=dur), np.average(q.ask_sz_00, weights=dur)))
    out = []
    for sess, r in rows.items():
        a = np.array(r)
        out.append({"asset": "USO", "session": sess, "n_windows": len(a), "mean_spread_bps": a[:, 0].mean(),
                    "median_spread_bps": np.median(a[:, 0]), "mean_spread_px": a[:, 1].mean(),
                    "mean_bid_sz": a[:, 2].mean(), "mean_ask_sz": a[:, 3].mean(),
                    "source": "mbp-1, 60 s before each post, time-weighted"})
    return pd.DataFrame(out)


# --- markouts -----------------------------------------------------------------------------------------------
def quote_at(q: pd.DataFrame, t: pd.Timestamp):
    """Last valid quote at or before t within the lookback, else None."""
    q = q[(q.ts_event <= t) & (q.ts_event > t - LOOKBACK - EPS)]
    return None if q.empty else q.iloc[-1]


def markouts(posts: pd.DataFrame, data: dict, spread: dict) -> pd.DataFrame:
    rows = []
    for p in posts.itertuples():
        for name, (dataset, _, sym) in FEEDS.items():
            feed = "GLBX" if dataset == "GLBX.MDP3" else name
            ref = None
            for h, s in HORIZONS.items():
                t = p.t0 + pd.Timedelta(seconds=s)
                tag = h if h in ("5m", "10m", "30m", "1h") else "near"
                rec = {"post_id": p.id, "t0_utc": p.t0, "post_type": p.post_type, "asset": name, "horizon": h,
                       "horizon_s": s, "target_utc": t,
                       "session": uso_session(p.t0) if name == "USO" else ("open" if globex_open(p.t0) else "closed")}
                df = data.get(f"{ckey(feed, dataset)}_{p.t0:%Y%m%dT%H%M%S%f}_{tag}")
                q = None
                if df is not None and OPEN[name](p.t0) and path_open(OPEN[name], p.t0, s):
                    d = df[(df.symbol == sym) & (df.bid_px_00 > 0) & (df.ask_px_00 > df.bid_px_00)]
                    q = quote_at(d.sort_values("ts_event"), t)
                if q is not None:
                    mid = (q.bid_px_00 + q.ask_px_00) / 2
                    if h == "0s":
                        ref = mid
                    rec.update(quote_ts=q.ts_event, bid=q.bid_px_00, ask=q.ask_px_00, bid_sz=q.bid_sz_00,
                               ask_sz=q.ask_sz_00, mid=mid, spread_px=q.ask_px_00 - q.bid_px_00,
                               spread_bps=(q.ask_px_00 - q.bid_px_00) / mid * 1e4)
                    if ref is not None:
                        rec["markout_px"] = mid - ref
                        rec["markout_bps"] = (mid - ref) / ref * 1e4
                        key = (name, "regular" if name == "USO" and rec["session"] == "regular"
                               else "extended" if name == "USO" else "all")
                        # in average spreads, measured in dollars: mid change ($) / average quoted spread ($)
                        rec["avg_spread_px"] = spread[key]
                        rec["markout_spreads"] = rec["markout_px"] / spread[key]
                rows.append(rec)
    return pd.DataFrame(rows)


def summarize(m: pd.DataFrame) -> pd.DataFrame:
    out = []
    for group, g in (("all_posts", m), ("warnings", m[m.post_type == "warning"])):
        for (asset, h), x in g.dropna(subset=["markout_bps"]).groupby(["asset", "horizon"], sort=False):
            out.append({"group": group, "asset": asset, "horizon": h, "n": len(x),
                        "mean_bps": x.markout_bps.mean(), "median_bps": x.markout_bps.median(),
                        "mean_px": x.markout_px.mean(), "mean_spread_px_at_t": x.spread_px.mean(),
                        "mean_abs_bps": x.markout_bps.abs().mean(), "mean_spreads": x.markout_spreads.mean(),
                        "median_spreads": x.markout_spreads.median(),
                        "t_stat": x.markout_bps.mean() / (x.markout_bps.std(ddof=1) / np.sqrt(len(x)))
                        if len(x) > 1 else np.nan})
    s = pd.DataFrame(out)
    s["horizon"] = pd.Categorical(s.horizon, list(HORIZONS), ordered=True)
    return s.sort_values(["group", "asset", "horizon"]).round(4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-only", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    posts = load_posts()
    print(f"{len(posts)} posts {posts.t0.min()} .. {posts.t0.max()}")
    print(posts.post_type.value_counts().to_string())
    js = jobs(posts)
    client = Client()
    s_start, s_end = WAR_START, posts.t0.max().normalize() + pd.Timedelta(days=1)
    if args.cost_only:
        print(f"{len(js)} mbp-1 windows")
        c = estimate_cost(client, js)
        c2 = avg_spread(client, s_start, s_end, cost_only=True)
        print(f"mbp-1 windows est ${c:.2f}; bbo-1m for average spread ${c2:.2f}; total ~${c + c2:.2f}")
        return

    sp = avg_spread(client, s_start, s_end, cost_only=False)
    sp["source"] = "bbo-1m"

    data, t = {}, time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(fetch, client, j): j for j in js}
        for i, f in enumerate(as_completed(futs), 1):
            data[futs[f][2]] = f.result()
            if i % 200 == 0 or i == len(js):
                print(f"  {i}/{len(js)} windows ({time.time() - t:.0f}s)", flush=True)

    # USO: bbo-1m minute samples (EQUS.MINI) showed $0.5-1 spreads in regular hours against 1-5 cents in tick data
    # 1-3 cents, so the minute samples are not usable; use the time-weighted spread over the 60 s before each
    # post instead (already downloaded, before the post can move anything)
    sp = pd.concat([sp[sp.asset != "USO"], uso_window_spread(posts, data)], ignore_index=True)
    OUT.mkdir(parents=True, exist_ok=True)
    sp.round(4).to_csv(OUT / "avg_spread.csv", index=False)
    print(sp.round(3).to_string(index=False))
    spread = {(r.asset, r.session): r.mean_spread_px for r in sp.itertuples()}

    m = markouts(posts, data, spread)
    m.to_csv(OUT / "markouts_long.csv", index=False)
    wide = m.pivot_table(index=["post_id", "t0_utc", "post_type", "asset"], columns="horizon",
                         values="markout_bps", observed=False)[list(HORIZONS)].reset_index()
    wide.round(3).to_csv(OUT / "markouts_wide_bps.csv", index=False)
    posts.to_csv(OUT / "posts.csv", index=False)
    s = summarize(m)
    s.to_csv(OUT / "summary.csv", index=False)
    with pd.option_context("display.width", 200):
        print(s.to_string(index=False))


if __name__ == "__main__":
    main()
