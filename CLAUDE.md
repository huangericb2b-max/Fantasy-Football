# Fantasy Football Edge

Eric's fantasy football analysis repo. Python package `ffedge` pulls nflverse data and computes the numbers; Claude reads the output, adds live news and coverage data from the web, and makes the calls.

League: 6-team dynasty on League Tycoon, team "Aubrey Merchant", full PPR. Settings live in `league.toml`; the roster lives in `roster.toml`. Read both before any lineup or waiver answer, and ask Eric to update `roster.toml` if it's empty or looks stale.

## Commands

Run with `uv run ffedge ...` (or `ffedge ...` inside the venv).

| Command | What it gives you |
|---|---|
| `ffedge status` | Current week, which games are final, how far each dataset goes |
| `ffedge refresh` | Force re-download of current-season data (cache refreshes every 6h anyway) |
| `ffedge whiteboard --roster` / `--players "A, B"` | Per-game Scheme / Trends / injury data sheet + projections, saved to `reports/` |
| `ffedge graphic --roster` / `--players "A, B"` | Visual matchup cards (HTML): role charts, target/run maps, defense zone maps, coverage, rank edges; opens in browser |
| `ffedge usage --players "A, B" [--weekly]` | Snap, target, air-yard, rush, red-zone shares and xFP, season vs last 4 |
| `ffedge usage --risers` | Biggest recent role growth (waiver radar) |
| `ffedge regression [--position WR] [--players ...]` | Points and TDs vs expected: buy-low and sell-high lists |
| `ffedge project --roster` / `--position RB` | Next-week projection with 80% range (league scoring) |
| `ffedge defense [--offense] [--position TE]` | Team defense/offense ranks or points allowed by position |
| `ffedge backtest` | How the projection model did on last season |

Slash commands in `.claude/commands/` wrap these into full workflows: `/whiteboard`, `/cards`, `/start-sit`, `/waivers`, `/trade`, `/update-scheme`.

## How to analyze

Follow `.claude/skills/fantasy-football-edge/SKILL.md`. Short version:

1. Run `ffedge status` first. State the as-of time (Eastern) and the latest week in the data. Don't call stats "this week's" if the dataset stops a week earlier.
2. Get the numbers from `ffedge`, not from memory. Use the web only for what the data can't have: injury/practice news after the nflverse pull, 2026 coverage rates (man/zone, MOFO/MOFC), and beat-reporter role news.
3. Role first, matchup second. The backtest shows matchup features barely move weekly accuracy; usage and expected points do most of the work. A great matchup doesn't rescue a 40% snap share.
4. Treat regression flags as a reason to look, not a verdict. Check whether QB, health or role changed.
5. Label every number as observed (nflverse), model output (`ffedge project`), web source (name + date), or judgment.

## Data limits to remember

- nflverse has no 2026 participation data. That means no 2026 man/zone, MOFO/MOFC, charted pressure, or route counts. Use `data/scheme_overrides.csv` for 2026 coverage (fill it with `/update-scheme`); 2025 numbers appear as a labeled baseline.
- Pressure in 2026 is a proxy: (sacks + QB hits) / dropbacks. Call it that.
- FTN charting (blitz rate, rushers, box count) usually runs a week behind pbp.
- xFP comes from ffverse's expected-points model, scored as standard full PPR with 4-pt passing TDs.
- The projection model knows nothing about this week's injuries or news.

## Writing style for Eric

Direct, opinionated, specific names and numbers. Lead with the call. No em dashes. Use contractions. No "Bold term: explanation" bullet lists. Don't open with scene-setting or close with a summary. He reads this on his phone, so keep each game tight. Matchup breakdowns follow Max Loeb's whiteboard format: Scheme, Trends, X-factors, Verdict.

## Code conventions

- Polars, not pandas, inside `ffedge/`.
- Every matchup/projection feature must only use games before the target week. Keep it that way; leakage makes the backtest lie.
- Add a test in `tests/` for any new scoring or feature logic. `pytest -m "not network"` runs offline.
- Don't commit `data/cache/`, `data/models/` or `reports/`.
