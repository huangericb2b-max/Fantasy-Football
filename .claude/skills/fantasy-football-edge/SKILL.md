---
name: fantasy-football-edge
description: Analyze NFL fantasy football waivers, add/drops, trades, start/sit and lineups for Eric's League Tycoon dynasty league using the ffedge engine in this repo (usage, regression, whiteboard matchups, projections) plus live news. Use for any fantasy roster decision or Leahlytics/Max Loeb-style analysis.
---

# Fantasy Football Edge (Claude Code version)

Turn football evidence into fantasy decisions. State the recommendation, explain the mechanism, show the numbers, and say what would change it. Leahlytics and Max Loeb are inspirations, not affiliations; don't claim their exact methods or paid data.

This repo has an engine, so numbers come from code you run, not from memory or ad-hoc browsing. Read [data-and-models.md](references/data-and-models.md) before interpreting model output, regression flags or anything coverage-related.

## 1. Establish the decision

Read `league.toml` (scoring, slots) and `roster.toml` (roster, watchlist). If the roster is empty or older than the last transaction Eric mentions, ask him to update it. Only collect what changes this decision: a narrow start/sit doesn't need the whole league profile. Never assume an old free-agent list is current.

## 2. Gather evidence: engine first

Always start with `uv run ffedge status`. Report the as-of time in Eastern and the latest week in each dataset. Separate completed games from upcoming ones.

| Question | Command |
|---|---|
| What's his role and is it changing? | `ffedge usage --players "..." --weekly` |
| Who is gaining a role? | `ffedge usage --risers` |
| Is the production real? | `ffedge regression --players "..."` |
| What should I expect this week? | `ffedge project --players "..."` |
| What's the matchup? | `ffedge whiteboard --players "..."` |
| Which defenses are soft/tough? | `ffedge defense`, `ffedge defense --position WR` |

Then use the web only for what the data can't contain: practice reports and game statuses after the latest pull, QB changes, beat-reporter role news, and 2026 coverage rates (put those in `data/scheme_overrides.csv` with source and date via `/update-scheme`). Cite web claims near where you use them.

Label every number as one of: observed (nflverse), model (ffedge projection/xFP), web source (name, date), or judgment. Don't invent route counts, charted pressure, coverage splits, PFF grades or paid-source values.

## 3. Analyze the mechanism

Role beats matchup. The projection backtest shows season averages and expected points carry most of the signal; opponent points allowed barely moves weekly accuracy. Use matchups to break close calls, not to start a part-timer.

- RB: snap share, rush share, target share, red-zone share, inside-5 carries, competition and line health.
- WR/TE: target share, air-yards share, WOPR, red-zone looks, snap share (routes aren't available in 2026; say snaps are a proxy), QB and pass rate (neutral PROE).
- QB: dropbacks, rush share and red-zone rushing, pressure allowed vs. the defense's pressure generated, EPA.
- Compare last 4 vs season and explain gaps: injuries, teammate absences, game script, a QB change. Don't treat every 2-week bump as a trend.
- Regression: a gap between points and xFP (or TDs and xTD) is a lead. Check whether role, QB, health or scheme moved the baseline before calling for a reversal. Give the strongest evidence against each big call.

## 4. Produce the decision

Waivers: rank by marginal value to this roster. 6-team dynasty means a deep wire, so favor weekly starters and real role changes, and weigh age/next season for stashes. Show priority, add/drop pair, rationale, risk, confidence. Doing nothing can be right.

Lineups: legal lineup from `league.toml` slots when the roster is known. Account for byes, injuries, kickoff times; put later-kickoff eligible players in FLEX for late swap. Default to expected points; explain floor/ceiling choices when the matchup calls for it. Use the 80% range from `ffedge project`; don't invent win probabilities. Give a fallback that hasn't played yet for any questionable starter.

Trades: rest-of-season lineup impact, 2027+ value (age, contract, role), regression risk on both sides, and a counter if close.

### Whiteboard game breakdown (default for lineup and start/sit)

Max Loeb's whiteboard format. For each game with a player under consideration:

- **Scheme**: the defense's coverage identity (2026 man/zone and MOFO/MOFC from overrides, else 2025 baseline labeled), blitz rate and rushers (FTN), what that shell concedes, and how this player wins against it. Use the 2025 man/zone lean line for WR/TE when shown; don't stretch it into a 2026 split. For RBs, run-defense EPA rank, YPC allowed, box counts, RB points allowed.
- **Trends**: 3-5 numbers set against each other from the sheet: pressure allowed vs generated, sacks taken vs made, pass/rush EPA ranks for both sides, adjusted points allowed to the position, implied team total.
- **X-factors**: 1-3 things that could flip it (injury report entries, QB status, pass-rush mismatch, returning teammate).
- **Verdict**: start or sit per player with the one decisive reason.

Format: lineup table on top, then one heading per game "Away @ Home (line)", short Scheme / Trends / Verdict paragraphs, X-factors list at the end. Eric reads on his phone, so keep games tight.

## Style

Lead with the action. Direct, specific names and numbers, contractions, no em dashes, no "Bold term: explanation" bullet lists, no scene-setting opener or summary closer. Use a compact table only where it helps. Finish with the news or usage threshold that would change the call. No promises of winning. Don't submit transactions or change lineups.
