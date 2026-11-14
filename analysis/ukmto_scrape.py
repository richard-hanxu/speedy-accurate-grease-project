"""Collect UKMTO alerts (warnings, attack reports, advisories, JMIC notes) since 2026-01-01 and flag oil-relevant ones.

ukmto.org sits behind a Cloudflare bot check, so this does NOT fetch from it directly. Everything comes from the
Internet Archive: the Wayback CDX index lists every archived PDF under /-/media/ukmto/products/, and each PDF is
fetched from its archived copy. A product that was never archived is missing here; the run prints gaps in the
UKMTO sequence numbers (warnings and advisories share one NNN-26 sequence) so they can be filled by hand.

The PDF CreationDate is used as the issue time; the provenance work found it a close proxy, with UKMTO's
X post following 4-28 min later.

Usage:  python analysis/ukmto_scrape.py [--since 2026-01-01] [--refresh-index]
Writes: data/ukmto_alerts_2026.csv (all parsed products) and data/ukmto_alerts_2026_oil.csv (oil-relevant only)
"""

from __future__ import annotations

import argparse
import hashlib
import io
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
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ukmto_x import parse_warning_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE_DIR = Path(os.environ.get("UKMTO_CACHE", ROOT / "analysis" / "cache" / "ukmto"))
# captures exist under both hosts; bare ukmto.org ones are usually 301s to www, which Wayback follows
PREFIXES = ["www.ukmto.org/-/media/ukmto/products/", "ukmto.org/-/media/ukmto/products/"]
CDX = "https://web.archive.org/cdx/search/cdx"
UA = "hormuz-research/0.1 (academic research; reads archived copies via archive.org)"

# filename patterns for alert products; summaries, dashboards, statistics and weekly VRA overviews are skipped
ALERT_RE = re.compile(r"warning|attack|advisory|jmic-advisory|update-\d{3}|infonote|information-note|notice")
SKIP_RE = re.compile(r"summary_report|dashboard|statistics|vra_overview|guidance")

# --- oil relevance -------------------------------------------------------------------------------------------
KINETIC = ["attack", "struck", "strike", "projectile", "missile", "drone", "uav", "usv", "explosion", "explosive",
           "blast", "mine", "fire", "ablaze", "damage", "casualt", "killed", "sunk", "sank", "sinking", "hijack",
           "seized", "seizure", "boarded", "boarding", "detained", "diverted", "disabled", "hit by", "splash", "bang",
           "shots fired", "warning shots"]
CLOSURE = ["blockade", "closure", "closed", "suspend", "not permitted", "prohibited", "denied passage",
           "strait of hormuz is open", "reopen", "soh open", "southern corridor", "restriction", "transit passage"]
ENERGY = ["tanker", "lng", "lpg", "crude", "oil", "product carrier", "chemical", "vlcc", "terminal", "pipeline",
          "refinery", "offshore platform", "fpso", "spm", "loading"]
REGION = ["hormuz", "persian gulf", "arabian gulf", "gulf of oman", "red sea", "bab el", "bab-el", "bab al",
          "gulf of aden", "arabian sea", "suez", "fujairah", "khor fakkan", "ras tanura", "jubail", "yanbu",
          "ras laffan", "qatar", "kuwait", "basra", "al-faw", "al faw", "kharg", "bandar abbas", "jask", "musandam",
          "kumzar", "dubai", "jebel ali", "abu dhabi", "ruwais", "das island", "bahrain", "hodeidah", "ras isa",
          "mukalla", "aden", "duqm", "sohar", "muscat", "salalah", "socotra", "jeddah", "umm qasr", "iraq",
          "saudi", "uae", "united arab emirates", "emirates", "sharjah", "ras al khaimah", "mina saqr", "khasab",
          "sirik", "oman", "iran", "yemen", "somalia", "eritrea", "djibouti", "israel", "egypt"]


def hits(text: str, terms) -> list:
    return [t for t in terms if re.search(r"\b" + re.escape(t), text)]


def relevance(text: str, heading: str):
    """(tier, matched terms). high = kinetic event on an energy vessel/asset, or a closure/blockade notice;
    medium = kinetic event in an oil chokepoint region; low = everything else (approaches, GNSS, admin)."""
    # every warning ends "report any suspicious activity to UKMTO"; drop it so it does not read as a low-tier cue
    t = re.sub(r"report any suspicious[^.]*\.?", " ", f"{heading} {text}".lower())
    k, c, e, r = hits(t, KINETIC), hits(t, CLOSURE), hits(t, ENERGY), hits(t, REGION)
    matched = sorted(set(k + c + e + r))
    if k and e:
        return "high", matched
    if c and (r or e):
        return "high", matched
    if k and r:
        return "medium", matched
    return "low", matched


# --- archive access -----------------------------------------------------------------------------------------
class ArchiveOnly(urllib.request.HTTPRedirectHandler):
    """Follow redirects only within archive.org, so a capture of a 301 never sends us to the live ukmto.org."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).netloc.endswith("archive.org"):
            return super().redirect_request(req, fp, code, msg, headers, newurl)
        raise urllib.error.HTTPError(newurl, 404, "redirect leaves archive.org", headers, fp)


OPENER = urllib.request.build_opener(ArchiveOnly)


def get(url: str, tries: int = 6, timeout: int = 90) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with OPENER.open(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            code = getattr(e, "code", None)
            if code == 404:
                raise
            wait = 10 * (i + 1)
            print(f"  retry {i + 1}/{tries} in {wait}s ({code or e})", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"failed after {tries} tries: {url}")


def wayback_index(since: str, refresh: bool) -> pd.DataFrame:
    """One row per distinct archived product PDF: normalised url, earliest 200 snapshot timestamp, original url."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "cdx_products.json"
    if refresh or not path.exists():
        rows = []
        for prefix in PREFIXES:
            q = urllib.parse.urlencode({"url": prefix, "matchType": "prefix", "from": since[:4], "output": "json",
                                        "fl": "original,timestamp,statuscode", "filter": "statuscode:[23]..",
                                        "limit": 50000})
            got = json.loads(get(f"{CDX}?{q}", timeout=180) or b"[]")
            rows += got[1:] if rows else got
        path.write_text(json.dumps(rows))
    rows = json.loads(path.read_text())
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["key"] = (df.original.str.replace(r"^https?://(www\.)?", "www.", regex=True)
                 .str.replace(r"\?.*$", "", regex=True).str.replace(":80/", "/", regex=False).str.lower())
    df = df[df.key.str.endswith(".pdf")]
    # prefer a direct 200 capture, else the earliest redirect capture
    df["rank"] = (df.statuscode != "200").astype(int)
    return df.sort_values(["rank", "timestamp"]).groupby("key", as_index=False).first()


def fetch_pdf(row) -> bytes | None:
    f = CACHE_DIR / "pdf" / (hashlib.sha1(row.key.encode()).hexdigest()[:16] + ".pdf")
    if f.exists():
        return f.read_bytes()
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        # a redirect capture holds no PDF: ask Wayback for its nearest capture of the canonical www URL instead
        src = row.original if row.statuscode == "200" else f"https://{row.key}"
        b = get(f"https://web.archive.org/web/{row.timestamp}id_/{src}")
    except Exception as e:  # noqa: BLE001 - keep going, the gap is reported
        print(f"  fetch failed {row.key}: {e}", file=sys.stderr)
        return None
    time.sleep(1.0)  # be polite to archive.org
    if not b.startswith(b"%PDF"):
        print(f"  not a PDF: {row.key}", file=sys.stderr)
        return None
    f.write_bytes(b)
    return b


# --- parsing ------------------------------------------------------------------------------------------------
def pdf_time(v) -> pd.Timestamp | None:
    m = re.match(r"D:(\d{14})(Z|[+-]\d{2}'?\d{2}'?)?", str(v or ""))
    if not m:
        return None
    ts = pd.Timestamp(m.group(1)[:8] + "T" + m.group(1)[8:])
    off = (m.group(2) or "Z").replace("'", "")
    if off != "Z":
        sign = 1 if off[0] == "+" else -1
        ts -= sign * pd.Timedelta(hours=int(off[1:3]), minutes=int(off[3:5] or 0))
    return ts.tz_localize("UTC")


DATE_RE = r"\d{1,2}(?:\s*[/-]\s*\d{1,2}\s*[/-]\s*|\s+[A-Za-z]{3,9}\s+)\d{4}"
TIME_RE = r"\d{4}\s*(?:UTC|Z|LT|hrs)|\d{1,2}:\d{2}(?:\s*UTC)?|TBC|UNK\w*"


def field(text: str, name: str, pattern: str) -> str:
    """First value matching pattern after the label. The labels and values can come out of the PDF as separate
    blocks ("Incident Date: Incident Time: Source: 13 OCT 2026 1830UTC Verified"), so search forward."""
    m = re.search(name + r"\s*:", text, re.I)
    if not m:
        return ""
    v = re.search(pattern, text[m.end():m.end() + 200], re.I)
    return re.sub(r"\s+", " ", v.group(0)).strip() if v else ""


def stamp(date: str, hhmm: str):
    """'17 Feb 2026' + '1016UTC' -> UTC timestamp; None when either part is missing or TBC."""
    t = re.match(r"(\d{1,2}):?(\d{2})", str(hhmm or ""))
    if not date or not t:
        return None
    try:
        d = pd.to_datetime(date, dayfirst=True)
    except (ValueError, TypeError):
        return None
    return (d + pd.Timedelta(hours=int(t[1]), minutes=int(t[2]))).tz_localize("UTC")


def parse(row, b: bytes) -> dict:
    r = PdfReader(io.BytesIO(b))
    meta = r.metadata or {}
    text = "\n".join((p.extract_text() or "") for p in r.pages)
    flat = re.sub(r"\s+", " ", text)
    name = row.key.rsplit("/", 1)[1]
    # reference: "177-26 - ATTACK" in the body, else from the file name
    m = re.search(r"\b(\d{3})[-_ ]?(26)\s*[-–]\s*([A-Z][A-Z /&-]{2,40}?)(?=\s+(?:Incident|UKMTO|[A-Z][a-z])|$)", flat)
    if "jmic" in name:
        # JMIC numbers its own notes; "update-NNN-jmic-advisory-note" is the rolling situation report
        product = "jmic_update" if re.search(r"update", name) else "jmic_note"
        seq, heading = None, ""
    else:
        product = ("warning" if re.search(r"warning|attack", name) else "advisory" if "advisory" in name
                   else "other")
        mf = (re.search(r"(?:warning|attack|advisory)[-_ ]*(?:attack[-_ ]*|incident[-_ ]*|update[-_ ]*\d{3}[-_])?"
                        r"(\d{3})(?:[-_ ]?26|[-_]update|\.pdf)", name)
              or re.search(r"ukmto[-_ ]*(\d{3})[-_]26", name))
        seq = int(m.group(1)) if m else (int(mf.group(1)) if mf else None)
        heading = m.group(3).strip() if m else ""
    issued = pdf_time(meta.get("/CreationDate"))
    # warnings: "UKMTO (has) received ..." up to the stock "Vessels are advised" line; other products: from the first
    # sentence-like start
    body = (parse_warning_text(text)["description"] if product in ("warning", "advisory") else "") or \
        re.sub(r"^.*?(UKMTO has|UKMTO received|JMIC|Vessels|The )", r"\1", flat, count=1)
    tier, matched = relevance(flat, heading)
    if product == "jmic_update":
        tier = "context"  # cumulative situation reports, not a new event
    return {
        "ref": f"{seq:03d}-26" if seq else "", "seq": seq, "product": product, "heading": heading,
        "update": bool(re.search(r"update", name)),
        "issued_utc": issued.isoformat().replace("+00:00", "Z") if issued is not None else "",
        "modified_utc": (pdf_time(meta.get("/ModDate")) or pd.NaT),
        "file_date": (re.match(r"(\d{8})", name) or [None, ""])[1],
        # older layout: Incident Date/Time; most 2026 warnings: Report Date/Time (when UKMTO got the report)
        "incident_date": field(text, "Incident Date", DATE_RE), "incident_time": field(text, "Incident Time", TIME_RE),
        "report_date": field(text, "Report Date", DATE_RE), "report_time": field(text, "Report Time", TIME_RE),
        "source": field(text, "Source", r"Verified|Unverified|Third[- ]party|Not verified|Military authorities|"
                                        r"Master|CSO|Company Security Officer|Company|Flag State|Industry|UKMTO"),
        "oil_relevance": tier, "matched_terms": ";".join(matched),
        "description": body[:1500], "url": "https://" + row.key,
        "wayback": f"https://web.archive.org/web/{row.timestamp}/{row.original}",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-01")
    ap.add_argument("--refresh-index", action="store_true", help="re-query the Wayback CDX index")
    args = ap.parse_args()
    since = pd.Timestamp(args.since, tz="UTC")

    idx = wayback_index(args.since, args.refresh_index)
    name = idx.key.str.rsplit("/", n=1).str[1]
    idx = idx[name.str.contains(ALERT_RE) & ~name.str.contains(SKIP_RE)]
    print(f"{len(idx)} candidate alert PDFs in the Wayback index")

    out = []
    for i, row in enumerate(idx.itertuples(), 1):
        b = fetch_pdf(row)
        if b is None:
            continue
        try:
            rec = parse(row, b)
        except Exception as e:  # noqa: BLE001
            print(f"  parse failed {row.key}: {e}", file=sys.stderr)
            continue
        out.append(rec)
        if i % 25 == 0:
            print(f"  {i}/{len(idx)}")

    df = pd.DataFrame(out)
    df["issued"] = pd.to_datetime(df.issued_utc, utc=True, errors="coerce")
    # event time = incident time when given, else report time; lag = PDF issue time minus that
    for kind in ("incident", "report"):
        df[f"{kind}_utc"] = [stamp(d, t) for d, t in zip(df[f"{kind}_date"], df[f"{kind}_time"])]
    df["event_utc"] = df.incident_utc.fillna(df.report_utc)
    df["event_time_kind"] = df.incident_utc.notna().map({True: "incident", False: "report"}).where(df.event_utc.notna())
    df["lag_hours"] = ((df.issued - pd.to_datetime(df.event_utc, utc=True)).dt.total_seconds() / 3600).round(2)
    df["event_utc"] = pd.to_datetime(df.event_utc, utc=True).dt.strftime("%Y-%m-%dT%H:%MZ")
    df = df.drop(columns=["incident_utc", "report_utc"])
    df = df[df.issued >= since].sort_values("issued").drop(columns="issued")
    # several files can carry the same product (re-uploads "-1", "-2"); keep the earliest issue of each file body
    df = df.drop_duplicates(subset=["ref", "update", "description"], keep="first")
    df.to_csv(DATA / "ukmto_alerts_2026.csv", index=False)
    oil = df[df.oil_relevance.isin(["high", "medium"])]
    oil.to_csv(DATA / "ukmto_alerts_2026_oil.csv", index=False)

    seqs = sorted(int(s) for s in df.seq.dropna().unique())
    missing = [n for n in range(1, max(seqs) + 1) if n not in seqs] if seqs else []
    print(f"\n{len(df)} products since {args.since}: {df.oil_relevance.value_counts().to_dict()}")
    print(f"wrote {DATA / 'ukmto_alerts_2026.csv'} and {DATA / 'ukmto_alerts_2026_oil.csv'} ({len(oil)} rows)")
    print(f"sequence numbers 1-{max(seqs) if seqs else 0}: {len(seqs)} found, {len(missing)} not archived: "
          f"{missing}")


if __name__ == "__main__":
    main()
