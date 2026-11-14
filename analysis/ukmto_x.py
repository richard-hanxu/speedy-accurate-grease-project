"""Real-time listener for "UKMTO WARNING" posts from @UK_MTO on X, with OCR of the attached warning image.

UKMTO's warning posts carry the text as an image, so each post is: snowflake ID -> exact post time (ms),
image -> local OCR (RapidOCR, ~1.5-2 s on 4 CPUs, model held in memory) -> ID / incident date / time / description.

X does not push a third party's posts to your webhook (the Account Activity API only covers accounts that
authorise your app), so this process is the bridge: it reads X and POSTs each parsed warning to --webhook.

Transports (both need an X API bearer token in X_BEARER_TOKEN, from developer.x.com; check current pricing):
  stream  filtered stream with rule  from:UK_MTO "UKMTO WARNING"   lowest latency (~seconds), needs stream access
  poll    user-timeline polling with since_id every --interval s    works on lower tiers, latency = interval

Usage:  python analysis/ukmto_x.py listen [--mode stream|poll] [--interval 60] [--webhook https://...]
        python analysis/ukmto_x.py ocr <image-or-pdf>     # test the extractor on a file
Appends to data/ukmto_x_warnings.csv (ID, datetime, incident_date, incident_time, description, ...).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = ROOT / "data" / "ukmto_x_warnings.csv"
API = "https://api.x.com/2"
HANDLE = "UK_MTO"
PREFIX = "UKMTO WARNING"
STREAM_RULE = f'from:{HANDLE} "{PREFIX}"'
COLUMNS = ["ID", "datetime", "incident_date", "incident_time", "description", "time_kind", "x_post_id", "x_url",
           "ocr_seconds"]
TWITTER_EPOCH_MS = 1288834974657

# OCR often drops spaces ("18OCT2026", "1830UTC"), so these allow optional whitespace
CODE_RE = re.compile(r"\b(\d{3})\s*[-–_]\s*(\d{2})\b")
DATE_RE = re.compile(r"\d{1,2}\s*(?:[A-Za-z]{3,9}|[/.-]\s*\d{1,2}\s*[/.-])\s*\d{4}")
TIME_RE = re.compile(r"\b\d{4}\s*(?:UTC|Z|LT|hrs)\b|\b\d{1,2}:\d{2}\b|\bTBC\b|\bUNK\w*", re.I)


def snowflake_time(post_id: int | str) -> datetime:
    """X post IDs encode the creation time in ms since the Twitter epoch."""
    return datetime.fromtimestamp(((int(post_id) >> 22) + TWITTER_EPOCH_MS) / 1000, tz=timezone.utc)


def iso_ms(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


# --- extraction ---------------------------------------------------------------------------------------------
_ENGINE = None


def ocr_lines(image) -> list[str]:
    """image: path, bytes or ndarray. Returns text lines top to bottom."""
    global _ENGINE
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR
    import io

    if _ENGINE is None:
        _ENGINE = RapidOCR()
    if isinstance(image, (bytes, bytearray)):
        image = Image.open(io.BytesIO(image))
    elif isinstance(image, (str, Path)):
        image = Image.open(image)
    arr = np.array(image.convert("RGB"))
    res, _ = _ENGINE(arr, use_cls=False)  # the warnings are never rotated; skipping the angle model saves ~20%
    return [r[1] for r in (res or [])]


def parse_warning_text(text: str) -> dict:
    """Pull ID / date / time / description out of warning text (OCR lines or PDF text)."""
    flat = re.sub(r"[ \t]+", " ", text)
    code = CODE_RE.search(flat)
    out = {"ID": f"{code.group(1)}-{code.group(2)}" if code else "", "incident_date": "", "incident_time": "",
           "time_kind": "", "description": ""}
    # labels and values come out as separate blocks ("Incident Date: Incident Time: Source: 18 OCT 2026 TBC"),
    # so take the first date / time found after the label
    for kind in ("Incident", "Report"):
        m = re.search(kind + r"\s*Date\s*:", flat, re.I)
        if not m:
            continue
        tail = flat[m.end():m.end() + 250]
        d, t = DATE_RE.search(tail), TIME_RE.search(tail)
        out.update(incident_date=re.sub(r"\s+", " ", d.group(0)).strip() if d else "",
                   incident_time=re.sub(r"\s+", "", t.group(0)).upper() if t else "", time_kind=kind.lower())
        break
    body = re.search(r"(UKMTO\s*(?:has\s*)?received.*?)(?=Vessels\s*are\s*advised|UKMTO\s*,?\s*whilst|$)", flat,
                     re.I | re.S)
    if body:
        out["description"] = re.sub(r"\s+", " ", body.group(1)).strip()
    return out


def extract(image) -> dict:
    t = time.perf_counter()
    rec = parse_warning_text("\n".join(ocr_lines(image)))
    rec["ocr_seconds"] = round(time.perf_counter() - t, 2)
    return rec


# --- X API --------------------------------------------------------------------------------------------------
def x_get(path: str, params: dict | None = None, stream: bool = False):
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        sys.exit("X_BEARER_TOKEN is not set (create an app at developer.x.com and put the token in .env)")
    url = f"{API}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    r = urllib.request.urlopen(req, timeout=None if stream else 30)
    return r if stream else json.loads(r.read())


def x_post(path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{API}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['X_BEARER_TOKEN']}",
                                          "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


TWEET_PARAMS = {"tweet.fields": "created_at,text,attachments", "expansions": "attachments.media_keys",
                "media.fields": "url,type"}


def user_id() -> str:
    return x_get(f"/users/by/username/{HANDLE}")["data"]["id"]


def media_urls(tweet: dict, includes: dict) -> list[str]:
    keys = (tweet.get("attachments") or {}).get("media_keys", [])
    media = {m["media_key"]: m for m in includes.get("media", [])}
    return [media[k]["url"] for k in keys if k in media and media[k].get("type") == "photo" and media[k].get("url")]


def handle_post(tweet: dict, includes: dict) -> dict | None:
    """Parse one post; None if it is not a UKMTO WARNING."""
    if not tweet.get("text", "").strip().upper().startswith(PREFIX):
        return None
    rec = {"x_post_id": tweet["id"], "datetime": iso_ms(snowflake_time(tweet["id"])),
           "x_url": f"https://x.com/{HANDLE}/status/{tweet['id']}"}
    urls = media_urls(tweet, includes)
    if urls:
        sep = "&" if "?" in urls[0] else "?"
        img = urllib.request.urlopen(f"{urls[0]}{sep}name=large", timeout=30).read()
        rec.update(extract(img))
    # the post text often carries the code too; use it if OCR missed it
    if not rec.get("ID"):
        m = CODE_RE.search(tweet["text"])
        rec["ID"] = f"{m.group(1)}-{m.group(2)}" if m else ""
    return rec


def append(rec: dict, path: Path = OUT_CSV):
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(rec)


def deliver(rec: dict, webhook: str | None):
    append(rec)
    print(json.dumps(rec), flush=True)
    if webhook:
        req = urllib.request.Request(webhook, data=json.dumps(rec).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:  # noqa: BLE001 - never let a bad webhook stop the listener
            print(f"webhook failed: {e}", file=sys.stderr)


def listen_stream(webhook: str | None):
    rules = x_get("/tweets/search/stream/rules").get("data", [])
    if not any(r["value"] == STREAM_RULE for r in rules):
        x_post("/tweets/search/stream/rules", {"add": [{"value": STREAM_RULE, "tag": "ukmto-warning"}]})
    backoff = 5
    while True:
        try:
            with x_get("/tweets/search/stream", TWEET_PARAMS, stream=True) as r:
                backoff = 5
                for line in r:
                    if not line.strip():
                        continue  # keep-alive
                    msg = json.loads(line)
                    if "data" in msg and (rec := handle_post(msg["data"], msg.get("includes", {}))):
                        deliver(rec, webhook)
        except Exception as e:  # noqa: BLE001 - reconnect with backoff, as X asks
            print(f"stream dropped ({e}); reconnecting in {backoff}s", file=sys.stderr)
            time.sleep(backoff)
            backoff = min(backoff * 2, 320)


def listen_poll(webhook: str | None, interval: int):
    uid = user_id()
    params = {**TWEET_PARAMS, "max_results": 5, "exclude": "retweets,replies"}
    since = (x_get(f"/users/{uid}/tweets", params).get("meta") or {}).get("newest_id")
    print(f"polling @{HANDLE} every {interval}s from post {since}", file=sys.stderr)
    while True:
        time.sleep(interval)
        try:
            page = x_get(f"/users/{uid}/tweets", {**params, "since_id": since, "max_results": 100})
        except Exception as e:  # noqa: BLE001
            print(f"poll failed: {e}", file=sys.stderr)
            continue
        for tweet in reversed(page.get("data", [])):  # oldest first
            if rec := handle_post(tweet, page.get("includes", {})):
                deliver(rec, webhook)
        since = (page.get("meta") or {}).get("newest_id", since)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    li = sub.add_parser("listen")
    li.add_argument("--mode", choices=["stream", "poll"], default="poll")
    li.add_argument("--interval", type=int, default=60, help="poll seconds; keep within your tier's rate limit")
    li.add_argument("--webhook", default=os.environ.get("UKMTO_WEBHOOK_URL"))
    oc = sub.add_parser("ocr")
    oc.add_argument("file")
    args = ap.parse_args()

    if args.cmd == "ocr":
        src = args.file
        if src.lower().endswith(".pdf"):  # render like the posted image, for testing against archived PDFs
            import fitz
            src = fitz.open(src)[0].get_pixmap(dpi=110).tobytes("png")
        print(json.dumps(extract(src), indent=2))
    elif args.mode == "stream":
        listen_stream(args.webhook)
    else:
        listen_poll(args.webhook, args.interval)


if __name__ == "__main__":
    main()
