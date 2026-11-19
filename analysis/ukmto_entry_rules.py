"""Cumulative P&L (bps) after each "UKMTO WARNING" post under two long-entry rules, WTI / Brent / USO.

  always_passive    buy 1 unit at the best bid at the post time (t0), assuming it always fills.
                    P&L(h) = mid(t0+h) - bid(t0)          (= mid-to-mid markout + half the spread)
  post_1m_delay5s   at t0+5s join the best bid B behind the size already resting there (Q). Filled if, by
                    t0+65s, sell-aggressor volume traded at B exceeds Q or any trade prints below B (CL/BZ: CME
                    trades; USO: NYSE Arca trades only). Otherwise cancel and buy at the ask at t0+65s.
                    P&L(h) = mid(t0+h) - entry price; horizons 5m..1h only, as at 1m the order may still be working.

bps = P&L / entry price * 1e4; spreads = P&L ($) / the asset's average quoted spread ($), as in
ukmto_posts_markouts.py. Win = P&L > 0.

Data: the mbp-1 windows and CME trades already cached by ukmto_posts_markouts.py / ukmto_passive_fills.py, plus
(cheap) quotes at t0+60..65s for all three, and NYSE Arca USO trades for t0+5..65s.

Outputs: analysis/output/ukmto_posts/warnings_only/<rule>[_since_<date>]/ (same charts and tables as
ukmto_warning_cumulative.py) and entry_rules_trades.csv (one row per warning x asset x rule).

Usage:  python analysis/ukmto_entry_rules.py [--start 2026-08-01] [--cost-only]
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import databento as db
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ukmto_warning_cumulative as cum  # noqa: E402
from hormuz_markouts import Client  # noqa: E402
from ukmto_passive_fills import trades_path  # noqa: E402
from ukmto_posts_markouts import CACHE, FEEDS, OUT, ckey  # noqa: E402

DELAY = pd.Timedelta(seconds=5)
POST_FOR = pd.Timedelta(seconds=60)
SRC = OUT / "warnings_only" / "markouts_long.csv"
B_HORIZONS = ["5m", "10m", "30m", "1h"]


def tkey(t0):
    return f"{t0:%Y%m%dT%H%M%S%f}"


def extra_jobs(t0s_by_asset: dict) -> list:
    """(path, kwargs) for every window still to download."""
    jobs = []
    s_q, e_q = DELAY + POST_FOR - pd.Timedelta(seconds=5), DELAY + POST_FOR + pd.Timedelta(milliseconds=1)
    glbx = sorted(set(t0s_by_asset["WTI"]) | set(t0s_by_asset["Brent"]))
    for t0 in glbx:
        jobs.append((CACHE / f"q65_GLBX_{tkey(t0)}.parquet",
                     dict(dataset="GLBX.MDP3", schema="mbp-1", stype_in="continuous", symbols=["CL.v.0", "BZ.v.0"],
                          start=t0 + s_q, end=t0 + e_q)))
    for t0 in t0s_by_asset["USO"]:
        jobs.append((CACHE / f"q65_USO-ARCX_{tkey(t0)}.parquet",
                     dict(dataset="ARCX.PILLAR", schema="mbp-1", stype_in="raw_symbol", symbols=["USO"],
                          start=t0 + s_q, end=t0 + e_q)))
        jobs.append((CACHE / f"trades_USO-ARCX_{tkey(t0)}.parquet",
                     dict(dataset="ARCX.PILLAR", schema="trades", stype_in="raw_symbol", symbols=["USO"],
                          start=t0 + DELAY, end=t0 + DELAY + POST_FOR + pd.Timedelta(seconds=1))))
    return [j for j in jobs if not j[0].exists()]


def fetch(client: Client, job):
    path, kw = job
    for attempt in range(5):
        try:
            df = client.get_range(**kw).to_df().reset_index()
            break
        except db.BentoServerError:
            if attempt == 4:
                raise
            time.sleep(10 * (attempt + 1))
    cols = (["ts_event", "symbol", "price", "size", "side"] if kw["schema"] == "trades"
            else ["ts_event", "symbol", "bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00"])
    (df[cols] if len(df) else pd.DataFrame(columns=cols)).to_parquet(path)


def last_quote(q: pd.DataFrame, t):
    q = q[(q.ts_event <= t) & (q.bid_px_00 > 0) & (q.ask_px_00 > q.bid_px_00)]
    return None if q.empty else q.sort_values("ts_event").iloc[-1]


def post_rule(asset: str, t0) -> dict | None:
    """Simulate the post-for-1-minute rule; returns entry price, fill flag, fill time."""
    sym = FEEDS[asset][2]
    feed = "GLBX" if asset in ("WTI", "Brent") else "USO"
    near = pd.read_parquet(CACHE / f"{ckey(feed, FEEDS[asset][0])}_{tkey(t0)}_near.parquet")
    near = near[near.symbol == sym]
    te = t0 + DELAY
    q = last_quote(near, te)
    if q is None:
        return None
    B, Q = q.bid_px_00, q.bid_sz_00
    tp = trades_path(t0) if feed == "GLBX" else CACHE / f"trades_USO-ARCX_{tkey(t0)}.parquet"
    tr = pd.read_parquet(tp)
    tr = tr[(tr.symbol == sym) & (tr.ts_event > te) & (tr.ts_event <= te + POST_FOR)].sort_values("ts_event")
    at_b = tr[np.isclose(tr.price, B) & (tr.side == "A")]
    filled = (at_b["size"].cumsum() > Q).any() or (tr.price < B - 1e-9).any()
    if filled:
        return {"entry": B, "filled": True}
    q65 = pd.read_parquet(CACHE / f"q65_{'GLBX' if feed == 'GLBX' else 'USO-ARCX'}_{tkey(t0)}.parquet")
    q2 = last_quote(pd.concat([near, q65[q65.symbol == sym]]), te + POST_FOR)
    if q2 is None:
        return None
    return {"entry": q2.ask_px_00, "filled": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="also restrict to posts from this date, e.g. 2026-08-01")
    ap.add_argument("--cost-only", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    m = pd.read_csv(SRC, dtype={"post_id": str})
    m["t0_utc"] = pd.to_datetime(m.t0_utc, utc=True)
    zero = m[(m.horizon == "0s")].dropna(subset=["mid"])
    t0s = {a: sorted(zero[zero.asset == a].t0_utc) for a in FEEDS}

    client = Client()
    jobs = extra_jobs(t0s)
    if args.cost_only:
        sample = jobs[:: max(1, len(jobs) // 30)]
        c = sum(client.metadata.get_cost(**kw) for _, kw in sample) / max(1, len(sample)) * len(jobs)
        print(f"{len(jobs)} small windows to fetch, est ${c:.2f}")
        return
    with ThreadPoolExecutor(args.workers) as ex:
        list(ex.map(lambda j: fetch(client, j), jobs))

    # per warning x asset x rule x horizon
    mid = m.set_index(["t0_utc", "asset", "horizon"]).mid
    avg_sp = m.dropna(subset=["avg_spread_px"]).groupby(["t0_utc", "asset"]).avg_spread_px.first()
    rows = []
    for r in zero.itertuples():
        a, t0 = r.asset, r.t0_utc
        sp = avg_sp.get((t0, a))
        pr = post_rule(a, t0)
        for h in cum.HORIZONS:
            mh = mid.get((t0, a, h))
            if mh is None or np.isnan(mh):
                continue
            entries = [("always_passive", r.bid, True)]
            if pr and h in B_HORIZONS:
                entries.append(("post_1m_delay5s", pr["entry"], pr["filled"]))
            for rule, px, filled in entries:
                pnl = mh - px
                rows.append({"rule": rule, "post_id": r.post_id, "t0_utc": t0, "asset": a, "horizon": h,
                             "entry_px": px, "passive_fill": filled, "mid_at_h": mh, "pnl_px": pnl,
                             "markout_bps": pnl / px * 1e4, "markout_spreads": pnl / sp if sp else np.nan,
                             "spread_px": r.spread_px})
    tr = pd.DataFrame(rows)
    tr.to_csv(OUT / "warnings_only" / "entry_rules_trades.csv", index=False)

    starts = [None] + ([args.start] if args.start else [])
    for rule, label, note in [
        ("always_passive", "markout, always filled passively at the bid",
         "Entry = best bid at the post, assumed always filled; P&L = mid at the horizon - entry."),
        ("post_1m_delay5s", "markout, post 1 min at bid (5 s delay), else take ask",
         "Entry: join the best bid 5 s after the post; if not filled within 60 s (queue model on trades), buy "
         "the ask at +65 s. P&L = mid at the horizon - entry."),
    ]:
        d = tr[tr.rule == rule]
        for st in starts:
            cum.START = pd.Timestamp(st or "2026-02-28", tz="UTC")
            cum.PERIOD = f"{cum.START:%-d %b} to 13 Nov 2026"
            cum.LABEL, cum.NOTE, cum.WIN = label, note, "P&L > 0 at +{h}"
            cum.DEST = OUT / "warnings_only" / (rule + (f"_since_{cum.START:%Y%m%d}" if st else ""))
            print(f"\n== {rule} {'since ' + st if st else 'full period'}")
            if rule == "post_1m_delay5s":
                dd = d[(d.t0_utc >= cum.START) & (d.horizon == "5m")]
                print("passive fill rate:", dd.groupby("asset").passive_fill.mean().round(3).to_dict())
            hz = cum.HORIZONS if rule == "always_passive" else B_HORIZONS
            cum.run(d[d.t0_utc >= cum.START], hz)


if __name__ == "__main__":
    main()
