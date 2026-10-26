# Agent Handoff: Oil Markets Research Project

Last updated: 2026-10-26. Written for a future agent picking up this work. Read this first, then `README.md` and `meetings/2026-10-03.md`.

## Project in one paragraph
This is a Traders@CMU student project. The goal is to:
1. Identify "trigger" events that move oil markets. The main focus is the 2026 Strait of Hormuz crisis.
2. Measure markouts after each event: mid-to-mid PnL in bps at 1s, 10s, 1m, 5m, 10m, 30m, 1h, end of day, and 1–7 days.
3. Compare markouts across futures, ETFs/equities and options.
4. Find which markets and which news sources move first.

Team split, from the 03 Oct meeting:
- **Abdd** is responsible for FT headline signals and the Databento markouts, starting with USO.
- **Richard** is responsible for finding the fastest news sources for Hormuz activity: UKMTO, Telegram, Facebook/Instagram groups, Truth Social. The questions are which source is first, which ones copy others, and how to tell new developments from repeated news.

## Background facts (as of 20 Oct 2026)
- **Timeline of the war so far:**
  - **28 Feb 2026:** a US–Israel war on Iran started, and the strait has been mostly closed since.
  - **April:** ceasefire, then a US blockade of Iranian ports.
  - **June:** the Islamabad MoU, an interim peace deal.
  - **8 Jul:** the truce collapsed.
  - **14 Jul:** the US blockade was reinstated.
  - **16–17 Aug:** the MoU expired.
- **Traffic:** around 4–30 transits per day, against about 85–138 before the war (the figure depends on the tracker).
- **Prices:** Brent is around $105–109, after spikes on attack waves and on Trump's 26 Sep rejection of Iran's "7-day plan".
- **Talks:** Iran says the 7-day plan is still on the table as of 18 Oct.

## Files (all in git unless noted)
| Path | What it is |
|---|---|
| `research/hormuz-timeline-2026-07-to-10.md` | Dated timeline of major events, 20 Jul – 20 Oct 2026, with background from Feb onward. ★ marks likely market-moving triggers. Includes a sources list. Dates were corrected after the provenance work. |
| `research/hormuz-attack-provenance.md` | **Main deliverable.** For about 55 attack-related events: the first public source, its category, the first-public UTC time, the lag from the incident, who named the ship and when, and who claimed the attack. Also has the headline findings and recommendations. |
| `research/provenance/batch1…5_*.md` | Per-event detail behind the summary: the full pickup sequence (who reported next and when), every source link, and per-event notes and caveats. |
| `databento_example.py` | **Untracked. Not written or reviewed by Claude**, probably the user's or Abdd's. Check before relying on it or committing it. |
| Claude scratchpad (outside the repo) | The UKMTO warning PDFs and JMIC advisory notes that the research agents downloaded. These are untrusted downloads and were deliberately not copied into the repo. Re-download them from ukmto.org if needed. |

Git: `main`, commit `858912e` ("Add Strait of Hormuz research…"). Nothing has been pushed. The user asks before commits and pushes, so don't commit or push unprompted.

## Key findings (from the provenance work)
1. **UKMTO is the first public source for about 87% of merchant-ship attacks** (39 of 45).
   - The PDF warnings on ukmto.org come out 4–28 minutes before UKMTO's posts on X (@UK_MTO).
   - UKMTO never names the ship or the attacker.
   - Its warning serials (e.g. `170-26`) are a clean de-duplication key: a new serial is a new incident, and "Update 001" is a revision.
2. **The exceptions:**
   - The UAE (WAM/MoFA) when ADNOC ships are hit.
   - India's foreign ministry (@MEAIndia) or DG Shipping when Indian crew are aboard.
   - An industry leak (EOS Risk) once.
3. **Ship names arrive 3–20 hours later.** They come mostly from Vanguard Tech (also Marisks, EOS Risk, Ambrey, owners, Singapore's MPA). JMIC names ships officially 2–5 days later.
4. **The lag between incident and report is large and growing.**
   - Fast cases take 10 minutes to 3 hours.
   - Many October warnings were 12–21 hours late, and four of the 11 Oct attacks came out more than 24 hours late.
   - UKMTO says attacked ships increasingly refuse to report.
   - **Store incident time and first-public time as separate columns.**
5. **Wires follow quickly.** Reuters came about 28 minutes after UKMTO, and AFP about 23 minutes; typically it's 1–3 hours. Squawk feeds (Newsquawk, investingLive) and OSINT X accounts (@sentdefender, Osint613) usually relay 1.5–3 hours later. **No X account was confirmed as first.** Telegram could not be timestamped, so it is still untested.
6. **Iranian state media (Tasnim, Fars, IRNA, Mehr) is first in three situations:**
   - IRGC claim-only events. All six were unconfirmed and are likely false or recycled: the mine claims, the REMUS drone capture, the MQ-9 shootdown, and Rezaei's "5–6 nightly".
   - Blasts from US strikes, about 6 hours before CENTCOM (Larak 30 Aug, Kharg 5 Sep).
   - A couple of first ship names (*Trend*, *Al Maqam*).
7. **US denials (CENTCOM) of IRGC claims lag by about 4.5 to 46 hours.** That makes "unverified claim → later denial" a natural test of whether the market trades unconfirmed news and then reverses.

## Methods that worked
- **X post time from the post ID:** `((id >> 22) + 1288834974657)` ms gives exact UTC.
- **UKMTO warning PDF creation time:** a close proxy for issue time. The URL pattern is `ukmto.org/-/media/ukmto/products/2026MMDD-ukmto_warning_NNN-26.pdf`. WebFetch gets a 403, but curl worked.
- **JMIC advisory notes** (`update-NNN-jmic-advisory-note-DD-month.pdf`) map UKMTO serials to ship names.
- **Timezone gotchas:**
  - Maritime Executive metadata is in US Eastern time.
  - Tasnim shows no timezone; assume Tehran (UTC+3:30).
  - CBS live-blog stamps are posting times, not event times.

## Market-data decision (discussed, not implemented)
- **Databento** (already in use) is the recommended source for historical tick data. Datasets:
  - `GLBX.MDP3` for CME CL/BZ futures and their options.
  - `XNAS.ITCH`/`DBEQ` for USO, XLE and the oil majors.
  - `OPRA.PILLAR` for equity options.
- **ICE Brent** is not covered by most vendors; budget for it separately.
- **IBKR** (Interactive Brokers) is not suitable for historical markouts. History is shallow, requests are rate-limited, timestamps are only to the second, and there is no order-book history. It **is** the right tool for live testing and for measuring our own order-to-exchange latency, which is a project goal.
- Other options mentioned: WRDS/TAQ through CMU, CME DataMine, Cboe DataShop, Polygon, AlgoSeek.

## Open caveats
- Iranian and US claims frequently conflict. Entries marked "(claim)" or claim-only are unverified.
- Prices in the timeline are as reported in the news and **not checked against tick data**. In particular, check the Brent anomaly between 23 Jul (about $100) and mid-Aug (about $84–90). It may be a contract roll.
- Several provenance rows are low confidence: STI Steadfast's name, Ghana Prosperity's timing, Al Maqam's ordering, Kazimah III (UKMTO or Fars first?), and Larak's ordering.
- Coverage ends on 20 Oct 2026. Nothing after that has been researched.

## Suggested next steps (not started)
1. Turn the ★ timeline events and the provenance rows into a CSV of trigger timestamps. Columns: incident_utc, first_public_utc, source, category, event_type, claim/confirmed, serial. This feeds Abdd's markout code.
2. Pull Databento CL/BZ/USO data around those timestamps, compute markout curves, and compare markouts measured from incident time with markouts measured from first-public time.
3. Build live monitors for the fast sources:
   - UKMTO's PDF index and the @UK_MTO X account.
   - @CENTCOM and @MEAIndia.
   - Tasnim and Fars English.
   - The Newsquawk headline feed.
   - Test Telegram channels (IRGC-affiliated ones and OSINT ones) to see whether they beat UKMTO.
4. Extend the timeline and provenance work past 20 Oct as new events happen.
