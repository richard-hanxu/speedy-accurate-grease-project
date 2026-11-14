"""Back-fill UKMTO WARNING posts from @UK_MTO since 2026-01-01 into data/ukmto_x_warnings_2026.csv.

Two routes:
  api   (X_BEARER_TOKEN set) read the timeline through the X API, keep posts starting "UKMTO WARNING", OCR each
        image with the same extractor as the live listener (analysis/ukmto_x.py). Exact.
  free  (default without a token) the X post text/images are not freely available, but the Internet Archive's
        index holds the IDs of most @UK_MTO post URLs, and an ID gives the post time to the millisecond.
        Warning content (ID, date, time, description) comes from the archived UKMTO PDFs
        (data/ukmto_alerts_2026.csv, made by analysis/ukmto_scrape.py). Each warning is matched to the first
        archived post in [PDF creation - 2 min, + 45 min]; UKMTO posts follow the PDF by ~4-28 min.
        `match` says how sure the pairing is; warnings with no archived post fall back to the PDF creation time.

Usage:  python analysis/ukmto_x_history.py [--route free|api] [--since 2026-01-01]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ukmto_x import HANDLE, TWEET_PARAMS, handle_post, iso_ms, snowflake_time, user_id, x_get  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ALERTS = ROOT / "data" / "ukmto_alerts_2026.csv"
OUT = ROOT / "data" / "ukmto_x_warnings_2026.csv"
CACHE_DIR = Path(os.environ.get("UKMTO_CACHE", ROOT / "analysis" / "cache" / "ukmto"))
CDX = "https://web.archive.org/cdx/search/cdx"
UA = "hormuz-research/0.1 (academic research; reads archived copies via archive.org)"
WINDOW = (-pd.Timedelta(minutes=2), pd.Timedelta(minutes=45))
COLUMNS = ["ID", "datetime", "incident_date", "incident_time", "description", "time_kind", "datetime_source",
           "x_post_id", "x_url", "pdf_issued_utc", "x_lag_min", "match"]


def cdx(url: str, tries: int = 6) -> list:
    q = urllib.parse.urlencode({"url": url, "matchType": "prefix", "output": "json", "fl": "original",
                                "collapse": "urlkey", "limit": 50000})
    for i in range(tries):
        try:
            req = urllib.request.Request(f"{CDX}?{q}", headers={"User-Agent": UA})
            return json.loads(urllib.request.urlopen(req, timeout=180).read() or b"[]")[1:]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  CDX retry {i + 1}/{tries} ({getattr(e, 'code', e)})", file=sys.stderr)
            time.sleep(15 * (i + 1))
    raise RuntimeError(f"CDX failed: {url}")


def archived_post_ids(since: pd.Timestamp) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "cdx_x_posts.json"
    if not path.exists():
        rows = []
        for host in ("twitter.com", "x.com", "mobile.twitter.com"):
            rows += cdx(f"{host}/{HANDLE}/status/")
        path.write_text(json.dumps(rows))
    ids = {int(m.group(1)) for (u,) in json.loads(path.read_text())
           for m in [re.search(r"/status/(\d{15,20})", u)] if m}
    df = pd.DataFrame({"x_post_id": sorted(ids)})
    df["t"] = pd.to_datetime([snowflake_time(i) for i in df.x_post_id], utc=True)
    return df[df.t >= since].reset_index(drop=True)


def free_route(since: pd.Timestamp) -> pd.DataFrame:
    if not ALERTS.exists():
        sys.exit(f"{ALERTS} missing: run analysis/ukmto_scrape.py first")
    a = pd.read_csv(ALERTS)
    w = a[a["product"] == "warning"].copy()
    w["issued"] = pd.to_datetime(w.issued_utc, utc=True)
    w = w[w.issued >= since].sort_values("issued")
    posts = archived_post_ids(since)
    print(f"{len(w)} warnings from PDFs, {len(posts)} archived @{HANDLE} post IDs since {since.date()}")

    used, out = set(), []
    for r in w.itertuples():
        cand = posts[(posts.t >= r.issued + WINDOW[0]) & (posts.t <= r.issued + WINDOW[1])
                     & ~posts.x_post_id.isin(used)]
        kind = "incident" if isinstance(r.incident_date, str) else "report" if isinstance(r.report_date, str) else ""
        ref = r.ref + (" UPDATE" if r.update else "") if isinstance(r.ref, str) else ""
        rec = {"ID": ref, "incident_date": getattr(r, f"{kind}_date", "") if kind else "",
               "incident_time": getattr(r, f"{kind}_time", "") if kind else "", "time_kind": kind,
               "description": r.description, "pdf_issued_utc": r.issued_utc}
        if len(cand):
            p = cand.iloc[0]
            used.add(p.x_post_id)
            rec.update(datetime=iso_ms(p.t.to_pydatetime()), datetime_source="x_post_id",
                       x_post_id=str(p.x_post_id), x_url=f"https://x.com/{HANDLE}/status/{p.x_post_id}",
                       x_lag_min=round((p.t - r.issued).total_seconds() / 60, 2),
                       match="unique" if len(cand) == 1 else f"first_of_{len(cand)}")
        else:
            rec.update(datetime=r.issued.strftime("%Y-%m-%dT%H:%M:%S.000Z"), datetime_source="pdf_creation",
                       match="no_archived_post")
        out.append(rec)
    return pd.DataFrame(out)


def api_route(since: pd.Timestamp) -> pd.DataFrame:
    uid = user_id()
    params = {**TWEET_PARAMS, "max_results": 100, "exclude": "retweets,replies",
              "start_time": since.strftime("%Y-%m-%dT%H:%M:%SZ")}
    out, token = [], None
    while True:
        page = x_get(f"/users/{uid}/tweets", {**params, **({"pagination_token": token} if token else {})})
        for tweet in page.get("data", []):
            if rec := handle_post(tweet, page.get("includes", {})):
                rec.update(datetime_source="x_post_id", match="api")
                out.append(rec)
        token = (page.get("meta") or {}).get("next_token")
        if not token:
            break
    return pd.DataFrame(out).sort_values("datetime")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", choices=["free", "api"], default="api" if os.environ.get("X_BEARER_TOKEN") else "free")
    ap.add_argument("--since", default="2026-01-01")
    args = ap.parse_args()
    since = pd.Timestamp(args.since, tz="UTC")

    df = api_route(since) if args.route == "api" else free_route(since)
    df = df.reindex(columns=COLUMNS)
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT}: {len(df)} warnings; datetime from X post ID for "
          f"{(df.datetime_source == 'x_post_id').sum()}, from PDF creation for "
          f"{(df.datetime_source == 'pdf_creation').sum()}")
    if args.route == "free":
        print(df.match.str.replace(r"_\d+$", "_N", regex=True).value_counts().to_string())
        print("lag PDF -> X post (min):", df.x_lag_min.describe().round(1).to_dict())


if __name__ == "__main__":
    main()
