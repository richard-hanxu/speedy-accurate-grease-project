"""Would a passive 1-lot bid placed after a UKMTO WARNING post have filled, and how did filled bids do?

For each "UKMTO WARNING" post (analysis/output/ukmto_posts/warnings_only) and each reaction delay L:
  entry   at t0+L join the best bid B (from the cached mbp-1 window), behind the size already resting there (Q)
  fill    within FILL_WINDOW of entry, when sell-aggressor volume traded at B exceeds Q, or any trade prints
          below B (the level was cleared). Cancellations ahead of us are ignored, so the queue model is
          conservative (real fills come sooner).
  result  for filled bids, markout from the fill price B to the mid at t0+h, h in 5m/10m/30m/1h, in bps and $ per
          contract (CL = 1,000 bbl). Compared with an aggressive buy at the ask at t0+L.

Data: Databento GLBX.MDP3 trades for [t0, t0+L_max+FILL_WINDOW], plus the mbp-1 windows already cached by
analysis/ukmto_posts_markouts.py.

Usage:  python analysis/ukmto_passive_fills.py [--cost-only] [--asset WTI|Brent]
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
from hormuz_markouts import Client  # noqa: E402
from ukmto_posts_markouts import CACHE, OUT  # noqa: E402

DELAYS = [0, 1, 5, 15, 30]
FILL_WINDOW = pd.Timedelta(minutes=5)
HORIZONS = {"5m": 300, "10m": 600, "30m": 1800, "1h": 3600}
SYM = {"WTI": "CL.v.0", "Brent": "BZ.v.0"}
MULT = {"WTI": 1000, "Brent": 1000}
DEST = OUT / "warnings_only"


def trades_path(t0: pd.Timestamp) -> Path:
    return CACHE / f"trades_GLBX_{t0:%Y%m%dT%H%M%S%f}.parquet"


def span(t0):
    return t0, t0 + pd.Timedelta(seconds=max(DELAYS)) + FILL_WINDOW + pd.Timedelta(seconds=1)


def fetch_trades(client: Client, t0: pd.Timestamp) -> pd.DataFrame:
    p = trades_path(t0)
    if p.exists():
        return pd.read_parquet(p)
    s, e = span(t0)
    for attempt in range(5):
        try:
            data = client.get_range(dataset="GLBX.MDP3", schema="trades", stype_in="continuous",
                                    symbols=list(SYM.values()), start=s, end=e)
            break
        except db.BentoServerError:
            if attempt == 4:
                raise
            time.sleep(10 * (attempt + 1))
    df = data.to_df().reset_index()
    cols = ["ts_event", "symbol", "price", "size", "side"]
    df = df[cols] if len(df) else pd.DataFrame(columns=cols)
    df.to_parquet(p)
    return df


def quote_at(q: pd.DataFrame, t: pd.Timestamp):
    q = q[q.ts_event <= t]
    return None if q.empty else q.iloc[-1]


def simulate(asset: str, posts: pd.DataFrame, mids: pd.DataFrame) -> pd.DataFrame:
    sym, rows = SYM[asset], []
    for t0 in posts:
        near = CACHE / f"GLBX_{t0:%Y%m%dT%H%M%S%f}_near.parquet"
        if not near.exists() or not trades_path(t0).exists():
            continue
        q = pd.read_parquet(near)
        q = q[(q.symbol == sym) & (q.bid_px_00 > 0) & (q.ask_px_00 > q.bid_px_00)].sort_values("ts_event")
        tr = pd.read_parquet(trades_path(t0))
        tr = tr[tr.symbol == sym].sort_values("ts_event")
        for L in DELAYS:
            te = t0 + pd.Timedelta(seconds=L)
            qq = quote_at(q, te)
            if qq is None:
                continue
            B, A, Q = qq.bid_px_00, qq.ask_px_00, qq.bid_sz_00
            w = tr[(tr.ts_event > te) & (tr.ts_event <= te + FILL_WINDOW)]
            at_b = w[(np.isclose(w.price, B)) & (w.side == "A")]
            cum = at_b["size"].cumsum()
            t_q = at_b.ts_event[cum > Q].iloc[0] if (cum > Q).any() else pd.NaT  # queue ahead traded away
            below = w.ts_event[w.price < B - 1e-9]
            t_b = below.iloc[0] if len(below) else pd.NaT
            t_fill = min([t for t in (t_q, t_b) if pd.notna(t)], default=pd.NaT)
            rec = {"asset": asset, "t0_utc": t0, "delay_s": L, "bid": B, "ask": A, "queue_ahead": Q,
                   "filled": pd.notna(t_fill), "fill_s": (t_fill - te).total_seconds() if pd.notna(t_fill) else np.nan,
                   "fill_by": "queue" if pd.notna(t_fill) and t_fill == t_q else "price_through" if pd.notna(t_fill) else ""}
            for h in HORIZONS:
                mid = mids.get((t0, h))
                if mid is None or np.isnan(mid):
                    continue
                rec[f"passive_{h}_bps"] = (mid - B) / B * 1e4 if rec["filled"] else np.nan
                rec[f"aggr_{h}_bps"] = (mid - A) / A * 1e4
            rows.append(rec)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-only", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    m = pd.read_csv(DEST / "markouts_long.csv", parse_dates=["t0_utc"])
    m = m[m.asset.isin(SYM)]
    posts = sorted(m.dropna(subset=["mid"]).t0_utc.unique())
    posts = [pd.Timestamp(t) for t in posts]
    client = Client()
    todo = [t for t in posts if not trades_path(t).exists()]
    if args.cost_only:
        c = sum(client.metadata.get_cost(dataset="GLBX.MDP3", schema="trades", stype_in="continuous",
                                         symbols=list(SYM.values()), start=span(t)[0], end=span(t)[1])
                for t in todo[:20])
        print(f"{len(todo)} trade windows; est ${c / max(1, min(20, len(todo))) * len(todo):.2f}")
        return
    with ThreadPoolExecutor(args.workers) as ex:
        list(ex.map(lambda t: fetch_trades(client, t), todo))

    res = []
    for asset in SYM:
        mm = m[(m.asset == asset) & m.horizon.isin(HORIZONS)]
        mids = {(r.t0_utc, r.horizon): r.mid for r in mm.itertuples()}
        res.append(simulate(asset, posts, mids))
    r = pd.concat(res, ignore_index=True)
    r.to_csv(DEST / "passive_fills.csv", index=False)

    out = []
    for (asset, L), g in r.groupby(["asset", "delay_s"]):
        f = g[g.filled]
        row = {"asset": asset, "delay_s": L, "n": len(g), "fill_rate_pct": g.filled.mean() * 100,
               "fill_10s_pct": (g.fill_s <= 10).mean() * 100, "fill_60s_pct": (g.fill_s <= 60).mean() * 100,
               "median_fill_s": f.fill_s.median(), "median_queue_ahead": g.queue_ahead.median()}
        for h in HORIZONS:
            row[f"passive_{h}"] = f[f"passive_{h}_bps"].mean()
            row[f"aggr_{h}"] = g[f"aggr_{h}_bps"].mean()
            row[f"passive_win_{h}"] = (f[f"passive_{h}_bps"] > 0).mean() * 100
        out.append(row)
    s = pd.DataFrame(out).round(2)
    s.to_csv(DEST / "passive_fills_summary.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 50):
        print(s.to_string(index=False))


if __name__ == "__main__":
    main()
