"""Markouts of CME oil and S&P 500 futures around Strait of Hormuz news events.

Markout(h) = (mid(t0 + h) - mid(t0)) / mid(t0) * 1e4, in bps, where t0 is the
first-public time of the news (data/hormuz_events.csv) and mid is the quoted
top-of-book midpoint from Databento GLBX.MDP3 mbp-1 (every book update, ns
timestamps). mid(t) is the last valid quote with ts_event <= t.

Significance per (contract, horizon):
  * one-sample t-test of the event markouts against 0;
  * matched placebo test: the same clock time on nearby non-event weekdays.
    The event mean is compared with the distribution of means built by
    drawing one placebo day per event (10,000 draws).

Usage:  python analysis/hormuz_markouts.py [--group attack] [--precision all|second]
Needs DATABENTO_API_KEY in the environment (see .env). If that key runs out of credit (HTTP 402), the run
switches to DATABENTO_API_KEY_PERSONAL and carries on.
"""

import argparse
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import databento as db
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
EVENTS_CSV = ROOT / "data" / "hormuz_events.csv"
OUT_DIR = ROOT / "analysis" / "output" / "databento"
# keep the tick cache on disk outside /tmp (tmpfs is wiped on reboot) and outside the repo
CACHE_DIR = Path(os.environ.get("MARKOUT_CACHE", Path.home() / ".cache" / "speedy-grease" / "cache"))
API_KEY_VARS = ["DATABENTO_API_KEY", "DATABENTO_API_KEY_PERSONAL"]  # used in this order

DATASET = "GLBX.MDP3"
SCHEMA = "mbp-1"
# Volume-leading continuous contracts, so a roll never leaves us in an illiquid expiring month.
CONTRACTS = {
    "CL.v.0": "WTI crude (CL)",
    "BZ.v.0": "Brent crude (BZ)",
    "HO.v.0": "Heating oil (HO)",
    "RB.v.0": "RBOB gasoline (RB)",
    "ES.v.0": "S&P 500 E-mini (ES)",
}
COLORS = {  # reference categorical palette, slots 1-5 in fixed order
    "CL.v.0": "#2a78d6",
    "BZ.v.0": "#eb6834",
    "HO.v.0": "#1baf7a",
    "RB.v.0": "#eda100",
    "ES.v.0": "#e87ba4",
}
HORIZON_SETS = {
    "standard": {
        "-10m": -600, "-5m": -300, "-1m": -60, "0s": 0, "1s": 1, "5s": 5, "10s": 10,
        "30s": 30, "1m": 60, "5m": 300, "10m": 600, "30m": 1800, "1h": 3600,
    },
    # sub-second set for the Trump posts, whose reaction starts 20-130 ms after the post
    "ms": {
        "-10s": -10, "-5s": -5, "-1s": -1, "-500ms": -0.5, "-100ms": -0.1, "-50ms": -0.05, "-10ms": -0.01,
        "0s": 0, "10ms": 0.01, "50ms": 0.05, "100ms": 0.1, "500ms": 0.5, "1s": 1,
    },
}
HORIZONS = HORIZON_SETS["standard"]  # switched by --horizons in main()
FETCH_SPAN = (-600, 3600)  # cached windows always cover the standard set, whatever set is active
PAD = pd.Timedelta(minutes=2)  # extra data before the earliest horizon so mid(t0-10m) has a quote
N_PLACEBO_DAYS = 8
N_PERM = 10_000


def globex_open(ts: pd.Timestamp) -> bool:
    """CME Globex: Sun 18:00 ET to Fri 17:00 ET, daily halt 17:00-18:00 ET."""
    et = ts.tz_convert("America/New_York")
    wd, hm = et.weekday(), et.hour + et.minute / 60
    if wd == 5:  # Saturday
        return False
    if wd == 6:  # Sunday
        return hm >= 18
    if wd == 4:  # Friday
        return hm < 17
    return not (17 <= hm < 18)


def window_open(t0: pd.Timestamp, offsets) -> np.ndarray:
    """True for each horizon whose target time, and the whole path from t0 to it, is in session."""
    ok = []
    for s in offsets:
        lo, hi = sorted([t0, t0 + pd.Timedelta(seconds=s)])
        grid = pd.date_range(lo, hi, freq="1min").append(pd.DatetimeIndex([hi]))
        ok.append(all(globex_open(g) for g in grid))
    return np.array(ok)


class Client:
    """Databento client that moves to the next key in API_KEY_VARS when the current one is out of credit."""

    def __init__(self):
        self.keys = [(v, os.environ[v]) for v in API_KEY_VARS if os.environ.get(v)]
        if not self.keys:
            raise SystemExit(f"none of {API_KEY_VARS} is set")
        self.i = 0
        self.lock = threading.Lock()
        self.hist = db.Historical(self.keys[0][1])
        self.metadata = self.hist.metadata

    def get_range(self, **kw):
        while True:
            hist, i = self.hist, self.i
            try:
                return hist.timeseries.get_range(**kw)
            except db.BentoClientError as e:
                if e.http_status != 402:
                    raise
                with self.lock:  # several download threads can hit the limit at once; switch only once
                    if self.i == i:
                        if i + 1 >= len(self.keys):
                            raise
                        self.i = i + 1
                        print(f"  {self.keys[i][0]} is out of credit; switching to {self.keys[i + 1][0]}",
                              flush=True)
                        self.hist = db.Historical(self.keys[i + 1][1])


def window_path(t0: pd.Timestamp) -> Path:
    return CACHE_DIR / f"{SCHEMA}_{t0.strftime('%Y%m%dT%H%M%S')}.parquet"


def fetch_window(client: Client, t0: pd.Timestamp) -> pd.DataFrame:
    start = t0 + pd.Timedelta(seconds=FETCH_SPAN[0]) - PAD
    end = t0 + pd.Timedelta(seconds=FETCH_SPAN[1]) + pd.Timedelta(seconds=5)
    path = window_path(t0)
    if path.exists():
        return pd.read_parquet(path)
    for attempt in range(5):  # the gateway occasionally 504s on large windows
        try:
            data = client.get_range(
                dataset=DATASET, schema=SCHEMA, stype_in="continuous",
                symbols=list(CONTRACTS), start=start, end=end,
            )
            break
        except db.BentoServerError:
            if attempt == 4:
                raise
            time.sleep(10 * (attempt + 1))
    df = data.to_df().reset_index()[["ts_event", "symbol", "bid_px_00", "ask_px_00"]]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


def markouts_for(df: pd.DataFrame, t0: pd.Timestamp) -> pd.DataFrame:
    """Rows = contract, columns = horizon label, values in bps (NaN when closed / no quote)."""
    offsets = list(HORIZONS.values())
    is_open = window_open(t0, offsets) if globex_open(t0) else np.zeros(len(offsets), bool)
    targets = np.array([t0 + pd.Timedelta(seconds=s) for s in offsets], dtype="datetime64[ns]")
    out = {}
    for sym in CONTRACTS:
        q = df[(df.symbol == sym) & (df.bid_px_00 > 0) & (df.ask_px_00 > df.bid_px_00)]
        q = q.sort_values("ts_event")
        ts = q.ts_event.values.astype("datetime64[ns]")
        mid = ((q.bid_px_00 + q.ask_px_00) / 2).values
        row = np.full(len(offsets), np.nan)
        if len(ts):
            idx = np.searchsorted(ts, targets, side="right") - 1
            valid = idx >= 0
            px = np.where(valid, mid[np.clip(idx, 0, None)], np.nan)
            ref = px[offsets.index(0)]
            row = (px - ref) / ref * 1e4
        row[~is_open] = np.nan
        out[sym] = row
    return pd.DataFrame(out, index=list(HORIZONS)).T


def placebo_times(t0: pd.Timestamp, event_dates: set) -> list:
    """Same UTC clock time on the nearest weekdays that are not event days and are in session."""
    found = []
    for k in range(1, 30):
        for sign in (-1, 1):
            t = t0 + pd.Timedelta(days=sign * k)
            if t.date() in event_dates or not globex_open(t):
                continue
            if t > pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1):
                continue
            found.append(t)
        if len(found) >= N_PLACEBO_DAYS:
            break
    return found[:N_PLACEBO_DAYS]


def summarize(ev: pd.DataFrame, placebo: dict, rng) -> pd.DataFrame:
    """ev: MultiIndex (event_id, contract) x horizon. placebo: event_id -> same-shaped frame."""
    rows = []
    for sym in CONTRACTS:
        e = ev.xs(sym, level="contract")
        for h in HORIZONS:
            x = e[h].dropna()
            n = len(x)
            mean = x.mean() if n else np.nan
            se = x.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
            if h == "0s" or (n > 1 and (x == 0).all()):
                # 0s is 0 by construction, and an all-zero horizon (no quote change yet) is a null
                # result, not a missing one: report t=0, p=1 so the chart has no gap
                t, p = 0.0, 1.0
            else:
                t, p = (stats.ttest_1samp(x, 0.0) if n > 1 and x.std() > 0 else (np.nan, np.nan))
            # matched placebo: one random same-time weekday per contributing event
            pools = []
            for eid in x.index:
                pl = placebo.get(eid)
                if pl is not None:
                    v = pl.loc[pl.index == sym, h].dropna().values
                    if len(v):
                        pools.append(v)
            p_plc = np.nan
            if h == "0s":
                p_plc = 1.0
            elif len(pools) == n and n > 0:
                draws = np.column_stack([rng.choice(v, N_PERM) for v in pools]).mean(axis=1)
                p_plc = (np.sum(np.abs(draws) >= abs(mean)) + 1) / (N_PERM + 1)
            rows.append(dict(contract=sym, horizon=h, n=n, mean_bps=mean, se_bps=se,
                             t_stat=t, p_ttest=p, p_placebo=p_plc,
                             hit_rate=(x > 0).mean() if n else np.nan))
    return pd.DataFrame(rows)


def plot(summary: pd.DataFrame, title: str, path: Path, stats: bool = True) -> None:
    """stats=False drops the t-stat panel and the significance rings: average markouts only."""
    labels = list(HORIZONS)
    xs = np.arange(len(labels))
    if stats:
        fig, (ax, ax_t) = plt.subplots(2, 1, figsize=(12, 8.5), dpi=150, sharex=True,
                                       gridspec_kw={"height_ratios": [3, 1.3]})
    else:
        fig, ax = plt.subplots(figsize=(12, 6.5), dpi=150)
        ax_t = ax  # x-axis labels go on the single panel
    fig.patch.set_facecolor("#fcfcfb")
    ends = []
    for sym, name in CONTRACTS.items():
        s = summary[summary.contract == sym].set_index("horizon").loc[labels]
        m = s.mean_bps.values
        ax.plot(xs, m, color=COLORS[sym], lw=2, marker="o", ms=5, label=name, zorder=3)
        if stats:
            ax_t.plot(xs, s.t_stat.values, color=COLORS[sym], lw=1.5, marker="o", ms=4, zorder=3)
            # without placebo days (--placebo-days 0) the ring is the t-test alone
            has_plc = s.loc[s.index != "0s", "p_placebo"].notna().any()
            sig = (s.p_ttest < 0.05).values & ((s.p_placebo < 0.05).values if has_plc else True)
            ax.scatter(xs[sig], m[sig], s=120, facecolors="none", edgecolors="#0b0b0b", lw=1.2, zorder=4)
        last = np.where(~np.isnan(m))[0]
        if len(last):
            ends.append([m[last[-1]], xs[last[-1]], sym.split(".")[0]])
    # direct end labels, nudged apart so close series stay legible
    ends.sort()
    span = np.diff(ax.get_ylim())[0]
    for k in range(1, len(ends)):
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + 0.045 * span)
    for y, x, lab in ends:
        ax.annotate(lab, (x, y), xytext=(10, 0), textcoords="offset points", va="center",
                    fontsize=9, color="#52514e", annotation_clip=False)
    ax.set_ylim(top=max(ax.get_ylim()[1], ends[-1][0] + 0.03 * span) if ends else None)
    for a in {ax, ax_t}:
        a.set_facecolor("#fcfcfb")
        a.axhline(0, color="#8a8984", lw=0.8)
        a.axvline(labels.index("0s"), color="#8a8984", lw=0.8, ls="--")
        a.grid(axis="y", color="#e6e5e0", lw=0.6)
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            a.spines[sp].set_color("#c3c2b7")
        a.tick_params(colors="#52514e")
    if stats:
        for lvl in (-1.96, 1.96):
            ax_t.axhline(lvl, color="#8a8984", lw=0.8, ls=":")
        ax_t.set_ylabel("t-stat (dotted: ±1.96)", color="#52514e")
    ax.text(labels.index("0s"), ax.get_ylim()[1], " news first public", va="top", fontsize=8, color="#52514e")
    ax_t.set_xticks(xs, labels)
    ax_t.set_xlim(-0.4, len(labels) - 0.1)
    ax_t.set_xlabel("Horizon relative to first-public time (categorical spacing)", color="#52514e")
    ax.set_ylabel("Average mid-to-mid markout (bps)", color="#52514e")
    ax.set_title(title, loc="left", fontsize=12, color="#0b0b0b")
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=9, ncol=len(CONTRACTS))
    ax.set_title(title, loc="left", fontsize=12, color="#0b0b0b", pad=28)
    has_plc = summary.loc[summary.horizon != "0s", "p_placebo"].notna().any()
    ring = ("p<0.05 on both the t-test and the matched same-time placebo test" if has_plc
            else "p<0.05 on the t-test (no placebo test in this run)")
    fig.text(0.01, 0.01, (f"Black rings: {ring}. " if stats else "")
             + "Mid = (best bid + best ask)/2. Source: Databento GLBX.MDP3 mbp-1.",
             fontsize=8, color="#52514e")
    fig.tight_layout(rect=(0, 0.025, 1, 1))
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def chart_title(args, n: int) -> str:
    prec = "second-precision timestamps only" if args.precision == "second" else "all timestamps"
    ukmto = {"ukmto_high,ukmto_medium,ukmto_low": "UKMTO Warnings",
             "ukmto_high": "UKMTO Warnings: high oil relevance",
             "ukmto_medium": "UKMTO Warnings: medium oil relevance",
             "ukmto_update": "UKMTO Warning Updates"}
    if args.group in ukmto:
        return f"{ukmto[args.group]}\nAverage markout from the X post time (n={n} events, {prec})"
    label = {"attack": "confirmed ship attacks", "claim": "IRGC claim-only events",
             "trump_hawkish": "Trump hawkish Truth Social posts",
             "trump_dovish": "Trump dovish Truth Social posts",
             "ukmto_high,ukmto_medium,ukmto_low": "UKMTO warnings (X post time)",
             "ukmto_high": "UKMTO warnings, high oil relevance (X post time)",
             "ukmto_medium": "UKMTO warnings, medium oil relevance (X post time)",
             "ukmto_update": "UKMTO warning updates (X post time)"}.get(args.group, args.group)
    prec = "second-precision timestamps only" if args.precision == "second" else "all timestamps"
    return f"Average markout after Strait of Hormuz news: {label}\n(n={n} events, {prec})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(EVENTS_CSV), help="event CSV (e.g. data/trump_events.csv)")
    ap.add_argument("--group", default="attack",
                    help="event group from the CSV (attack, claim, trump_hawkish, trump_dovish)")
    ap.add_argument("--precision", default="all", choices=["all", "second"])
    ap.add_argument("--cost-only", action="store_true", help="price the windows not yet cached, then stop")
    ap.add_argument("--placebo-days", type=int, default=N_PLACEBO_DAYS)
    ap.add_argument("--workers", type=int, default=4, help="parallel window downloads")
    ap.add_argument("--no-stats", action="store_true", help="chart averages only: no t-stat panel or rings")
    ap.add_argument("--contracts", help="comma list of roots to keep, e.g. CL,BZ,ES (default: all)")
    ap.add_argument("--replot", action="store_true", help="redraw the chart from the saved summary CSV")
    ap.add_argument("--horizons", default="standard", choices=list(HORIZON_SETS))
    args = ap.parse_args()
    global HORIZONS, CONTRACTS
    HORIZONS = HORIZON_SETS[args.horizons]
    if args.contracts:
        keep = args.contracts.upper().split(",")
        CONTRACTS = {k: v for k, v in CONTRACTS.items() if k.split(".")[0] in keep}

    events = pd.read_csv(args.events, parse_dates=["first_public_utc"])
    # placebo days avoid every known event day: this file's and the main Hormuz event list's
    main_events = pd.read_csv(EVENTS_CSV, parse_dates=["first_public_utc"])
    all_dates = {t.date() for t in pd.concat([events, main_events]).first_public_utc}
    sel = events[events.group.isin(args.group.split(","))]
    if args.precision == "second":
        sel = sel[sel.precision == "second"]
    sel = sel[[globex_open(t) for t in sel.first_public_utc]]

    tag = f"{args.group.replace(',', '+')}_{args.precision}" + ("_noplacebo" if args.placebo_days == 0 else "") + ("" if args.horizons == "standard" else f"_{args.horizons}")
    if args.replot:
        summary = pd.read_csv(OUT_DIR / f"markout_summary_{tag}.csv")
        zero = (summary.horizon == "0s") | ((summary.mean_bps == 0) & (summary.se_bps.fillna(0) == 0))
        summary.loc[zero, ["t_stat", "p_ttest"]] = [0.0, 1.0]
        summary.loc[summary.horizon == "0s", "p_placebo"] = 1.0
        summary.to_csv(OUT_DIR / f"markout_summary_{tag}.csv", index=False, float_format="%.4f")
        plot(summary, chart_title(args, len(sel)), OUT_DIR / f"markouts_{tag}.png", stats=not args.no_stats)
        return

    client = Client()
    plc_times = {r.event_id: placebo_times(r.first_public_utc, all_dates)[:args.placebo_days]
                 for r in sel.itertuples()}

    if args.cost_only:
        todo = sorted({t for r in sel.itertuples() for t in [r.first_public_utc] + plc_times[r.event_id]
                       if not window_path(t).exists()})
        cost = 0.0
        for t in todo:
            cost += client.metadata.get_cost(
                dataset=DATASET, schema=SCHEMA, stype_in="continuous", symbols=list(CONTRACTS),
                start=t + pd.Timedelta(seconds=FETCH_SPAN[0]) - PAD,
                end=t + pd.Timedelta(seconds=FETCH_SPAN[1] + 5))
        print(f"{len(sel)} events, {len(todo)} windows to download (events + placebo days), "
              f"estimated cost ${cost:.2f}")
        return

    todo = sorted({t for r in sel.itertuples() for t in [r.first_public_utc] + plc_times[r.event_id]
                   if not window_path(t).exists()})
    if todo:  # download in parallel first; the loop below then reads the cache
        print(f"downloading {len(todo)} windows ({args.workers} at a time)", flush=True)
        t_start = time.perf_counter()
        with ThreadPoolExecutor(args.workers) as pool:
            futs = [pool.submit(fetch_window, client, t) for t in todo]
            for k, f in enumerate(as_completed(futs), 1):
                f.result()
                if k % 25 == 0 or k == len(todo):
                    el = time.perf_counter() - t_start
                    print(f"  {k}/{len(todo)} windows, {el / 60:.1f} min elapsed, "
                          f"~{el / k * (len(todo) - k) / 60:.0f} min left", flush=True)

    ev_frames, placebo = {}, {}
    for r in sel.itertuples():
        t0 = r.first_public_utc
        print(f"{r.event_id}  t0={t0}")
        ev_frames[r.event_id] = markouts_for(fetch_window(client, t0), t0)
        if plc_times[r.event_id]:
            placebo[r.event_id] = pd.concat(
                {str(t): markouts_for(fetch_window(client, t), t) for t in plc_times[r.event_id]},
                names=["placebo_t", "contract"])
    ev = pd.concat(ev_frames, names=["event_id", "contract"])
    for eid in placebo:  # flatten placebo days into one pool per event
        placebo[eid] = placebo[eid].droplevel("placebo_t").rename_axis("contract")

    summary = summarize(ev, placebo, np.random.default_rng(0))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ev.to_csv(OUT_DIR / f"markouts_by_event_{tag}.csv", float_format="%.3f")
    summary.to_csv(OUT_DIR / f"markout_summary_{tag}.csv", index=False, float_format="%.4f")

    plot(summary, chart_title(args, len(sel)), OUT_DIR / f"markouts_{tag}.png", stats=not args.no_stats)

    pd.set_option("display.width", 200)
    print(summary.pivot(index="horizon", columns="contract", values="mean_bps").loc[list(HORIZONS)].round(2))
    print(summary.pivot(index="horizon", columns="contract", values="p_placebo").loc[list(HORIZONS)].round(3))


if __name__ == "__main__":
    main()
