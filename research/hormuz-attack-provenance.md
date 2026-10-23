# Hormuz Attacks: Where the First Report Came From (20 Jul – 20 Oct 2026)

Compiled 2026-10-20. This covers every attack-related event in [hormuz-timeline-2026-07-to-10.md](hormuz-timeline-2026-07-to-10.md), plus a few found during research. Per-event detail is in `provenance/batch1…5.md`: the full pickup sequence, every source link, and notes.

## How times were established
- **UKMTO warning PDFs** (ukmto.org): the PDF creation time is a close proxy for issue time. UKMTO's X post typically follows the PDF by **4–28 min**.
- **X posts**: exact UTC, decoded from the post ID (`(id >> 22) + 1288834974657` ms). Several were re-checked independently.
- **Articles**: page metadata (`datePublished`), converted to UTC. Watch out: Maritime Executive metadata is in US Eastern time, and Tasnim pages show no timezone (Tehran time assumed).
- `≤` = "no later than". The source had already published by the time the first article citing it appeared.
- Telegram and Tasnim/Fars originals could rarely be timestamped. **Absence of social-media "firsts" here partly reflects what is searchable, not necessarily reality.**

## Headline findings
1. **UKMTO is the first public source for ~87% of merchant-ship attacks** (39 of 45). The exceptions:
   - Gulf governments, when the victim is state-owned: UAE/WAM for ADNOC ships, 8 and 13 Aug.
   - The Indian government, when Indian crew are aboard: *Al Maryah*, 20 Sep; *On Peace*, 6 Oct.
   - One industry leak: *Al Salam II*.
   - One unresolved case: *Al Maqam*.
2. **UKMTO never names the ship or the attacker.** Names come from:
   - private risk firms (**Vanguard Tech**, Marisks, EOS Risk, Ambrey), usually **3–20 h** later;
   - owners or flag states (Singapore MPA, the Greek shipping ministry);
   - **JMIC**, officially, 2–5 days later.
3. **The incident-to-report lag varies widely and is getting worse.**
   - Fast cases take 10 min to 3 h (*Acers*: 40 min; *Minoan Pioneer*: UKMTO received it 10 min after the strike).
   - Many October warnings are "time-late": issued 12–21 h after the incident (warnings 172–175), or **>24 h** after it (166–169, four of the 11 Oct attacks).
   - UKMTO's 16 Oct weekly says most attacked ships now *refuse to report*. **For the markout study, record incident time and first-public time as separate columns.**
4. **Wires follow UKMTO fast.**
   - Reuters 28 min after (GFS Pride, 13 Oct). AFP ~23 min after (*Acers*).
   - Typically 1–3 h; slower (2–12 h) in August.
   - Squawk feeds (Newsquawk, investingLive) and OSINT X accounts (OSINTdefender/@sentdefender, Osint613) relay within ~1.5–3 h, and are rarely ahead of UKMTO itself.
5. **Iranian state media is first for three kinds of event:**
   - **IRGC claim-only events.** All six were IRGC-first and **none were ever neutrally confirmed**: mine claims on 2 Sep, 17 Oct and 20 Oct; the REMUS drone capture; the MQ-9 shootdown; Rezaei's "5–6 ships nightly".
   - **US strikes on Iranian territory or ships.** For Larak (30 Aug) and the Kharg tankers (5 Sep), Fars/SNN reported the blasts ~6 h before CENTCOM.
   - **Occasionally the first name for a ship.** The IRGC named *Trend* (17 Sep); a Tasnim video tied the name *Al Maqam* to its attack (11 Oct).
6. **IRGC claims about neutrally reported attacks usually come *after* UKMTO**, by ~1 h (20 Jul) to ~12–36 h (GFS Pride, El Gaia). **CENTCOM denials lag IRGC claims by ~4.5 h to ~46 h.** No US response to the MQ-9 claim was found.
7. **US-initiated actions**: CENTCOM announced first for *Lavine* (24 Jul). For *Vela Nova* (11 Aug), UKMTO and Vanguard were ~10 h ahead of CENTCOM's admission.

## Master table
Category key: **UKMTO/JMIC** = maritime security official; **Mil** = US military; **Firm** = private maritime security firm; **IR** = Iranian state/IRGC media; **Gov** = Gulf or other government; **Wire** = major news outlet. Lag = incident → first public report.

| Date | Event | First public source | Cat. | First public (UTC) | Lag | Who named the ship / when | Claim | Conf. |
|---|---|---|---|---|---|---|---|---|
| 20 Jul | *Kavomaleas*, *Acheloos*, *Kaifan* hit off Oman/Musandam | UKMTO | UKMTO | ≤00:15Z 20 Jul | ~2 h | Dynacom (owner), EOS Risk, Marisks, +14–20 h | IRGC/Tasnim generic claim ~1 h after UKMTO | Med |
| 24 Jul | *Lavine* disabled by US | CENTCOM | Mil | ≤21:59Z | — | AP/MarEx +6 h | US self-announced | High |
| 31 Jul | LNG *GasLog Shanghai* disabled | UKMTO 101-26 | UKMTO | ≤03:42Z 1 Aug | ~4 h | GasLog/Bloomberg +12–17 h | Unclaimed (an IRGC claim came 7 h *before* the strike) | Med |
| 3 Aug | *Minoan Pioneer* hit | UKMTO 104-26 | UKMTO | 22:10Z received / 23:40Z PDF | 10 min–1.7 h | Vanguard via MarEx +5 h | Unclaimed | High |
| 5 Aug | Two blasts near tanker SE of Kumzar | UKMTO 107-26 | UKMTO | ≤01:20Z 6 Aug | ~6 h | — | Unclaimed | Med |
| 8 Aug | ADNOC tanker hit by missile | ADNOC via WAM | Gov | ≤10:29Z | ~6–10 h | Never named | UAE blames IRGC | Med-High |
| 11 Aug | *Vela Nova* hit by US MH-60 Hellfires (Wikipedia says 12 Aug) | UKMTO | UKMTO | ≤09:08Z | — | Vanguard via gCaptain 11:16Z | US admitted on X at 18:57Z (~10 h later) | High |
| 13 Aug | ADNOC *Navig8 Messi*, *Tarif* hit by drones | UAE MoFA | Gov | 20:54Z | ~5 h | Seatrade, next morning | UAE blames IRGC | Med-High |
| 14 Aug | *Al Watan* hit | UKMTO 113-26 | UKMTO | ≤06:06Z 15 Aug | ~10 h | Lloyd's List, 17 Aug | Unclaimed | Med |
| 17–18 Aug | *Minoan Dignity* hit, 1 killed | UKMTO (via Reuters) | UKMTO | 03:28Z 18 Aug | ~8.5 h | Greek press / Vanguard, +7–13 h | Unclaimed | Med-High |
| 24 Aug | *Metro Venetian* disabled | UKMTO 120-26 | UKMTO | ~20:25–20:57Z | <1 h | eKathimerini, ~25 Aug | Unclaimed | High |
| 25 Aug | *Al Salam II* hit | EOS Risk / MarEx (UKMTO formal warning dated 27 Aug) | Firm | ~26 Aug afternoon | ~1 day | JMIC | Unclaimed | Med |
| 29 Aug | *Burgan* hit | UKMTO 122-26 (delayed) | UKMTO | 30 Aug, time not found | ~0.5–1 day | JMIC navwarning | Unclaimed | Med |
| 30 Aug | US strikes on Larak Island; IRGC hits Jordan bases | Fars/Tasnim (blasts) ≈ US official via wires | IR / Wire | 30 Aug, time not found | — | — | Both sides claimed their own strikes | Low |
| 31 Aug | *Sidr* (2 killed) and *Senegal Prosperity* hit | UKMTO 124-26 | UKMTO | 20:00Z | ~8 min | Marisks/Kpler via Reuters, next morning | IRGC mine claim came earlier the same day but doesn't match. Saudi Arabia blamed Iran ~40 h later | High |
| 2 Sep | IRGC: two tankers hit mines | IRGC via IRNA/Press TV | IR | ≤09:06Z | n/a | — | Claim-only, never confirmed | Med |
| 5 Sep | US hits 3 Iranian tankers; IRGC missiles at US carrier | Fars/SNN | IR | ≤07:27Z | — | CENTCOM named ships ~6.5 h later | Both sides claimed | Med |
| 9 Sep | *Hercules Star* hit off Dubai, 1 killed | UKMTO 130-26 | UKMTO | 02:48Z | — | Charterer via Reuters ~12:20Z | Unclaimed | High |
| 9 Sep | *New Andros* hit near Al-Faw | UKMTO 131-26 ≈ Iraqi port officials | UKMTO / Gov | 9 Sep, time not found | — | OSINT on X/Telegram, hours later | Unclaimed | Med |
| 12–13 Sep | *El Gaia* hit, 2 killed | UKMTO 134-26 | UKMTO | ≤09:49Z 13 Sep | ~0.5 day | CENTCOM on X, 14 Sep | IRGC said mine (after UKMTO); CENTCOM said drone, +1.5 days | Med |
| 16 Sep | *Trend* disabled + unnamed Panamanian tanker | UKMTO (unnamed) | UKMTO | time not found | — | **IRGC Navy named it**, ~21:00Z 17 Sep | IRGC claimed | Med |
| 18 Sep | *STI Steadfast* | UKMTO (via Reuters) | UKMTO | ≤07:28Z | — | No naming source found | None | Low |
| 20 Sep | LPG *Al Maryah*, 9 Indian crew | India DG Shipping | Gov | ≤07:13Z 21 Sep | <1 day | Indian media | None | Med |
| 21 Sep | *LR Stephanie* (Wikipedia says 22 Sep) | UKMTO | UKMTO | ≤10:58Z | — | Marisks via Reuters, +24 h | None | Med-High |
| 23 Sep | *Cape Dao* hit (sank 14 Oct) | UKMTO | UKMTO | same day | — | Oman MSC / India MEA, hours later | Unverified social media blamed the IRGC | Med-High |
| 27 Sep | IRGC claims capture of US REMUS 600 drone | IRGC on state TV | IR | ≤13:16Z | n/a | — | Claim-only; CENTCOM denied "shortly after" | Med |
| 28 Sep | *Al Funtas* (sailing dark) | UKMTO, via late third-party report | UKMTO | time not found | ~12–18 h | Lloyd's List, 29 Sep | None | Med |
| 29 Sep | *Mersin Prosperity*, *Sinbad*, *Al Ruwais* | UKMTO (delayed) | UKMTO | time not found | unclear | Vanguard | Only threats from Fars/IRGC | Med |
| 1 Oct | *Kazimah III* | UKMTO (third party) **or Fars** | UKMTO / IR | 17:50Z | — | Vanguard, 2 Oct | Fars framed it as an "unauthorised route" | Low-Med |
| 2 Oct | *Uhud* | UKMTO | UKMTO | ≤16:11Z | ≤5 h (strike 11:22Z) | Vanguard via Seatrade | None | Med-High |
| 3 Oct | *Ghana Prosperity* | UKMTO (delayed) | UKMTO | time not found | — | Industry sources, +2–3 days | None | Low |
| 4 Oct | *Lipsi*, *Cameroon Prosperity*, LPG *Gas Vela* | UKMTO 150-26 etc. | UKMTO | 17:16Z (*Gas Vela*), 19:07Z (*Cameroon Prosperity*) | — | NAVAREA IX (Pakistan) named *Lipsi* the same day | None | Med |
| 5 Oct | LNG *Maran Gas Mystras* | UKMTO 156-26 | UKMTO | 16:37Z | — | Greek shipping ministry / Maran | None | Med-High |
| 5–6 Oct | *On Peace*, 12 injured | **India MEA on X** | Gov | **10:15:06Z 6 Oct** | — | MEA (first post) | None | High |
| 7 Oct | *Acers* off Qatar | UKMTO 158-26 on X | UKMTO | **19:40:08Z** | **40 min** | Vanguard via Seatrade 01:48Z | None | High |
| 9 Oct | *Gem No. 2* off UAE | Security firm → UKMTO 160-26 | Firm / UKMTO | 11:34Z (to UKMTO) | 1.5 h | Vanguard via Seatrade 14:11Z | None | Med-High |
| 10 Oct | *Valthera* | UKMTO 162-26 on X | UKMTO | 22:09:00Z | 2 h 50 min | Vanguard | Possibly an IRGC "supertanker mine" claim (unconfirmed) | Med |
| 10 Oct | *Ocean Molica* (bulk carrier) disabled by US | CENTCOM on X | Mil | 00:06:54Z 11 Oct | — | CENTCOM | US | Med |
| 11 Oct | *Petro Dolphin*, 2 missing | UKMTO 165-26 ≈ India shipping minister | UKMTO / Gov | before 18:23Z | — | Indian officials | None | Med |
| 11 Oct | *Angola Prosperity* | UKMTO 164-26 | UKMTO | ≤13:26Z | ~1.5 h | Vanguard | Generic Tasnim claim (unconfirmed) | Med-High |
| 11 Oct | *Ever Vict*, *Kition M*, *DP World Kaveri* | UKMTO 167–169 ("time-late") | UKMTO | **18:22Z 12 Oct** (167) | **>24 h** | Vanguard, then JMIC 15 Oct | None | Med |
| 11 Oct | *Al Maqam* (VLCC, not a bulk carrier) | UKMTO 166-26 vs. Tasnim video | UKMTO / IR | time not found | — | **Tasnim video** | IRGC claimed | Low-Med |
| 10–11 Oct | Rezaei: "5–6 shuttle ships hit nightly" | Iranian state TV | IR | time not found | n/a | — | Blanket claim | Med |
| 13 Oct | *GFS Pride* (sank 14 Oct) | UKMTO 170-26 | UKMTO | **18:56Z**; Reuters 19:24Z | — | Vanguard/Marisks overnight | IRGC said mine ~12 h later; CENTCOM rebutted +46 h | High |
| 13 Oct | *Alfonso* | UKMTO 171-26 | UKMTO | 18:59Z | — | Vanguard, 14 Oct | Implied only | High |
| 13 Oct | *GFS Giselle* | UKMTO 172-26 | UKMTO | 10:14Z 14 Oct | **~17.5 h** | Singapore MPA ≤14:25Z | None | High |
| 13 Oct | *Al Saadiyat* | UKMTO 173-26 (Ambrey possibly earlier) | UKMTO | 10:14Z 14 Oct | **~17 h** | Vanguard; UKMTO weekly 16 Oct | None | Med |
| 16 Oct | Tanker hit 68 nm NE of Jubail | UKMTO 174-26 | UKMTO | 06:16Z 17 Oct | **~21 h** | — | None | High |
| 16 Oct | Tanker hit by RPG 78 nm NE of Jubail | UKMTO 175-26 | UKMTO | 07:23Z 17 Oct | ~12 h | — | None | High |
| 17 Oct | IRGC: supertanker hit a mine | Tasnim | IR | ~07:52Z | n/a | — | Claim-only; JMIC found "no substantiation" | Med |
| 17 Oct | LNG tanker fired on off Yemen (outside Hormuz) | UKMTO 176-26 | UKMTO | 13:14Z | 2.7 h | — | None | High |
| 18 Oct | Tug *JIF Barracuda* hit by two projectiles off Khor Fakkan | UKMTO 177-26 | UKMTO | 04:14Z | — | Vanguard via MarEx, 19 Oct | OSINT X account blamed IRGC (after UKMTO) | High |
| 20 Oct | IRGC: 2 tankers hit mines; then a >2M bbl supertanker | Tasnim; later Fars | IR | ~09:58Z; supertanker on Newsquawk 16:54Z | n/a | — | Claim-only. CENTCOM said "false" via Al Jazeera Arabic → Newsquawk 14:40Z | Med |
| 20 Oct | IRGC: MQ-9 shot down ("54th") | Iranian state media | IR | ≤06:02Z | n/a | — | Claim-only; no US response found | Med |

**Tally of 45 attacks on merchant ships (excluding claim-only events and US actions):**

| First public source | Attacks |
|---|---|
| UKMTO | 39 |
| Gulf government | 2 |
| Indian government | 2 |
| Industry | 1 |
| Unresolved | 1 |

## What this means for the news-aggregation work
- **Monitor directly, in order of value:**
  1. UKMTO: the warning PDFs on ukmto.org (minutes ahead of its X account) and the @UK_MTO X account.
  2. Vanguard Tech, Ambrey and EOS Risk, for ship names.
  3. Tasnim, Fars, Mehr and Sepah News, for IRGC claims.
  4. @CENTCOM, for US actions and denials.
  5. India's @MEAIndia and DG Shipping, Singapore MPA, and UAE WAM/MoFA, for victim-state announcements.
  6. Newsquawk, for the fastest English relay of both Iranian claims and CENTCOM denials.
- **Social media**: OSINT X accounts were never confirmed as first. They mostly relay UKMTO 1.5–3 h later, though they occasionally surface names or video first (*New Andros*). Telegram channels could not be timestamped, so they remain the main untested candidate for beating UKMTO.
- **Separating new events from repeats**: UKMTO warning serial numbers (e.g. 170-26 → 177-26) are a clean de-duplication key. A new serial means a new incident; "Update 001" means a revision. Iranian claims often recycle earlier strikes (e.g. 2 Sep after 31 Aug), so they need matching against UKMTO serials.
- **Trading signal hypothesis**: Iranian mine claims arrive with no neutral confirmation, and denials lag them by hours. That makes them a natural test of whether the market trades unverified claims and then reverses.

## Corrections to the earlier timeline found during this research
- *Vela Nova* (US Hellfire strike): 11 Aug, not 12 Aug.
- The tug attack is 18 Oct, not 20 Oct.
- The Jubail RPG incident was 16 Oct; the warnings went out 17 Oct.
- JMIC was already at "severe" on 8 Oct; it was not raised on 11 Oct.
- *Al Maqam* is a VLCC tanker. The disabled bulk carrier on 10–11 Oct was *Ocean Molica*, hit by the US.
- *On Peace*: the incident date is disputed (JMIC says 5 Oct, India says 6 Oct).
- *LR Stephanie*: the incident was 21 Sep; 22 Sep is when it was identified.
- The IRGC claim usually tied to *GasLog Shanghai* predates that strike by 7 h.
