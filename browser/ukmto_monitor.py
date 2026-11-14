
#!/usr/bin/env python3
"""Poll UKMTO recent incidents with Zendriver and email on newly published IDs."""

import asyncio
import json
import logging
import os
import re
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import zendriver as zd
from dotenv import load_dotenv

URL = "https://www.ukmto.org/recent-incidents"
INTERVAL_SECONDS = 15
LOCAL_TZ = ZoneInfo("America/New_York")  # EST in winter, EDT in summer
STATE_FILE = Path(__file__).resolve().parent / "ukmto_state.json"
LOG_FILE = Path(__file__).resolve().parent / "ukmto_alerts.jsonl"

# Load Gmail credentials from gmail_app.env in the current working directory.
# If launched elsewhere (e.g. systemd), also check next to this script.
for env_path in (Path(__file__).resolve().parent / "gmail_app.env", Path.cwd() / "gmail_app.env"):
    if env_path.is_file():
        load_dotenv(env_path, override=True)

# UKMTO page has headings such as "Attack UKMTO #204".
HEADING_RE = re.compile(
    r"(?m)^(Attack|Advisory|Suspicious Activity|Hijack|Piracy|"
    r"Armed Robbery|Incident|Other)\s+UKMTO\s+#(\d+)\s*$",
    re.IGNORECASE,
)
REPORT_COUNT_RE = re.compile(r"(?m)^\s*(\d+)\s+reports\s*$", re.I)


def now_eastern():
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def parse_incidents(page_text):
    """Parse incident cards from visible page text, not the abbreviated map links."""
    count_match = REPORT_COUNT_RE.search(page_text)
    if not count_match or int(count_match.group(1)) == 0:
        raise ValueError("Incident list empty or still loading (0 reports).")

    matches = list(HEADING_RE.finditer(page_text))
    if not matches:
        raise ValueError("No UKMTO incident headings found; page layout may have changed.")

    incidents = {}
    for i, match in enumerate(matches):
        block = page_text[match.end(): matches[i + 1].start() if i + 1 < len(matches) else None]
        # Discard footer text appended to the last incident.
        block = re.split(r"\n\s*Home\s*\n\s*About us\b", block, maxsplit=1, flags=re.I)[0]
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        incident_id = int(match.group(2))
        incidents[str(incident_id)] = {
            "id": incident_id,
            "category": match.group(1),
            "date": lines[0] if lines else "Unknown",
            "description": " ".join(lines[1:]) if len(lines) > 1 else "",
        }
    return incidents


def save_state(state):
    temp_file = STATE_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp_file.replace(STATE_FILE)


def send_email(incident, detected_at):
    sender = os.environ["UKMTO_GMAIL_USER"]
    password = os.environ["UKMTO_GMAIL_APP_PASSWORD"].replace(" ", "")
    recipient = os.getenv("UKMTO_ALERT_TO", "richardhanxu@gmail.com")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = f"[UKMTO NEW INCIDENT] #{incident['id']} - {incident['category']}"
    msg.set_content(
        f"New UKMTO incident detected at {detected_at} (America/New_York)\n"
        f"UKMTO ID: #{incident['id']}\n"
        f"Category: {incident['category']}\n"
        f"UKMTO incident date: {incident['date']}\n\n"
        f"{incident['description']}\n\n"
        f"Source: {URL}\n\n"
        "Detection time is when this monitor first observed the notice, "
        "not necessarily the incident or publication time.\n"
    )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)


def record_alert(incident, detected_at):
    with LOG_FILE.open("a", encoding="utf-8") as out:
        out.write(json.dumps({"detected_at_et": detected_at, **incident}, ensure_ascii=False) + "\n")


async def fetch_incidents(browser):
    tab = await asyncio.wait_for(browser.get(URL), timeout=45)
    # The site sometimes says "0 reports" before JS finishes loading.
    for _ in range(20):
        text = await tab.evaluate("document.body ? document.body.innerText : ''")
        try:
            return parse_incidents(text)
        except ValueError:
            await asyncio.sleep(1)
    raise RuntimeError("No valid incident list after waiting 20 seconds")


async def monitor():
    if not os.environ.get("UKMTO_GMAIL_USER") or not os.environ.get("UKMTO_GMAIL_APP_PASSWORD"):
        raise RuntimeError("Set UKMTO_GMAIL_USER and UKMTO_GMAIL_APP_PASSWORD before running")

    browser = await zd.start(
        headless=True,
        browser_executable_path=os.getenv("CHROME_PATH", "/usr/bin/google-chrome"),
        browser_args=["--disable-dev-shm-usage", "--window-size=1920,1080"],
    )
    try:
        while True:
            start = time.monotonic()
            try:
                incidents = await fetch_incidents(browser)
                ids = {int(i) for i in incidents}
                if not STATE_FILE.exists():
                    # First run: remember existing reports; do not spam historical alerts.
                    state = {"highest_seen_id": max(ids), "sent_ids": []}
                    save_state(state)
                    logging.info("Baseline: %d visible incidents; highest ID #%d. No alerts sent.",
                                 len(incidents), state["highest_seen_id"])
                else:
                    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                    highest = int(state["highest_seen_id"])
                    sent = set(state.get("sent_ids", []))
                    # Larger IDs are assumed to be newly published. Avoids spurious
                    # alerts if old paginated entries become visible later.
                    new_ids = sorted(i for i in ids if i > highest and i not in sent)
                    logging.info("Checked %d visible incidents; %d new", len(ids), len(new_ids))
                    for incident_id in new_ids:
                        incident = incidents[str(incident_id)]
                        detected_at = now_eastern()
                        await asyncio.to_thread(send_email, incident, detected_at)
                        record_alert(incident, detected_at)
                        sent.add(incident_id)
                        state["highest_seen_id"] = incident_id
                        state["sent_ids"] = sorted(sent)
                        save_state(state)
                        logging.info("EMAIL SENT: #%d at %s", incident_id, detected_at)
            except Exception:
                logging.exception("Check failed. Existing state preserved; retrying next minute")
            elapsed = time.monotonic() - start
            await asyncio.sleep(max(0, INTERVAL_SECONDS - elapsed))
    finally:
        await browser.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        print("Monitor stopped")
