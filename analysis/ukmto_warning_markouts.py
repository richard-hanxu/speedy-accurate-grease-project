"""Markouts restricted to @UK_MTO posts whose text contains "UKMTO WARNING" (exact, case-sensitive).

Reads the full-post outputs of analysis/ukmto_posts_markouts.py (run that first; no new data is downloaded)
and writes analysis/output/ukmto_posts/warnings_only/:
  posts.csv, markouts_long.csv, markouts_wide_bps.csv, summary.csv
  summary_bps.csv / summary_spreads.csv   assets as rows, horizons as columns (mean)

Usage:  python analysis/ukmto_warning_markouts.py [--pattern "UKMTO WARNING"]
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ukmto_posts_markouts import HORIZONS, OUT, POSTS, summarize  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default="UKMTO WARNING")
    args = ap.parse_args()

    raw = pd.DataFrame(json.load(open(POSTS)))
    keep = set(raw[raw.text.str.contains(args.pattern, regex=False)].id.astype(str))
    dest = OUT / "warnings_only"
    dest.mkdir(parents=True, exist_ok=True)

    posts = pd.read_csv(OUT / "posts.csv", dtype={"id": str})
    posts = posts[posts.id.isin(keep)]
    posts.to_csv(dest / "posts.csv", index=False)
    m = pd.read_csv(OUT / "markouts_long.csv", dtype={"post_id": str})
    m = m[m.post_id.isin(keep)]
    m.to_csv(dest / "markouts_long.csv", index=False)
    w = pd.read_csv(OUT / "markouts_wide_bps.csv", dtype={"post_id": str})
    w[w.post_id.isin(keep)].to_csv(dest / "markouts_wide_bps.csv", index=False)

    s = summarize(m)
    s = s[s.group == "all_posts"].drop(columns="group")
    s.to_csv(dest / "summary.csv", index=False)
    cols = list(HORIZONS)
    for v, name in (("mean_bps", "summary_bps.csv"), ("mean_spreads", "summary_spreads.csv")):
        t = s.pivot(index="asset", columns="horizon", values=v)[cols].loc[["WTI", "Brent", "USO"]]
        t.round(3).to_csv(dest / name)
    # win rate for a long entered at the post-time mid: share of markouts > 0 (ties = mid unchanged)
    x = m.dropna(subset=["markout_bps"])
    x = x[x.horizon != "0s"]
    g = x.groupby(["asset", "horizon"]).markout_bps
    wr = pd.DataFrame({"n": g.size(), "up": g.apply(lambda v: (v > 0).sum()), "flat": g.apply(lambda v: (v == 0).sum()),
                       "down": g.apply(lambda v: (v < 0).sum())}).reset_index()
    wr["win_rate_pct"] = wr.up / wr.n * 100
    wr["win_rate_ex_flat_pct"] = wr.up / (wr.up + wr.down) * 100
    wr["flat_pct"] = wr.flat / wr.n * 100
    wr.round(1).to_csv(dest / "win_rate.csv", index=False)
    hz = cols[1:]
    for v in ("win_rate_pct", "win_rate_ex_flat_pct", "flat_pct"):
        print(f"\n{v}")
        print(wr.pivot(index="asset", columns="horizon", values=v)[hz].loc[["WTI", "Brent", "USO"]].round(1).to_string())

    print(f'{len(posts)} posts containing "{args.pattern}" since 2026-02-28 ({len(keep)} in the whole file)')
    with pd.option_context("display.width", 200):
        for v in ("n", "mean_bps", "median_bps", "mean_spreads", "t_stat"):
            print(f"\n{v}")
            print(s.pivot(index="asset", columns="horizon", values=v)[cols].loc[["WTI", "Brent", "USO"]]
                  .round(2).to_string())
    print(f"\n-> {dest}")


if __name__ == "__main__":
    main()
