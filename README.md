# Fantasy Football Edge

My fantasy football analysis engine, built to run inside Claude Code. Python does the number crunching from free nflverse data; Claude adds the news, makes the calls and writes them up whiteboard-style.

## Setup (once)

```bash
git clone https://github.com/huangericb2b-max/Fantasy-Football.git
cd Fantasy-Football
uv sync              # or: python -m venv .venv && source .venv/bin/activate && pip install -e . pytest
uv run ffedge status # first run downloads ~5 seasons of data, takes a few minutes
```

Then edit `roster.toml` with my current players and double-check the `VERIFY` lines in `league.toml`.

## Using it with Claude Code

Open the folder with `claude` and use:

- `/whiteboard` - full Scheme / Trends / X-factors / Verdict breakdown for my roster
- `/whiteboard Ja'Marr Chase, Colston Loveland` - same, for specific players
- `/cards` - visual matchup cards with charts, opened in your browser
- `/start-sit Player A vs Player B`
- `/waivers <available players>`
- `/trade I give X / I get Y`
- `/update-scheme` - pull current man/zone and MOFO/MOFC rates into `data/scheme_overrides.csv`

Or just ask in plain English; `CLAUDE.md` and the project skill tell Claude how to use the engine.

## Commands on their own

```bash
uv run ffedge whiteboard --roster
uv run ffedge graphic --roster          # visual matchup cards in your browser
uv run ffedge usage --risers            # waiver radar
uv run ffedge regression --position WR  # buy-low / sell-high
uv run ffedge project --position RB --top 20
uv run ffedge defense --position TE     # points allowed to TEs
uv run ffedge backtest                  # how good is the model?
```

## What's in here

| Path | What |
|---|---|
| `ffedge/usage.py` | Snap, target, air-yard, rush and red-zone shares, xFP; season vs recent |
| `ffedge/regression.py` | Points and TDs vs expected, buy-low / sell-high flags |
| `ffedge/matchup.py` | Defense/offense profiles: EPA, pressure, blitz, box counts, coverage, points allowed |
| `ffedge/project.py` | Gradient-boosted projection model with 80% ranges, plus backtest |
| `ffedge/whiteboard.py` | Builds the per-game data sheet |
| `ffedge/graphics.py` | Matchup cards: hand-built SVG charts in one HTML page |
| `.claude/` | Slash commands, project skill, permissions |
| `league.toml`, `roster.toml` | League settings and my roster |
| `data/scheme_overrides.csv` | Current-season coverage rates from web sources |

## Known limits

nflverse stopped publishing participation data after 2025, so there's no free 2026 man/zone, MOFO/MOFC, charted pressure or route data. Coverage comes from `scheme_overrides.csv`, pressure uses a sacks+hits proxy, and receiver man/zone leans use 2025. The projection model beats a season average only slightly (2025 MAE 4.50 vs 4.52), which is about what weekly fantasy noise allows. Details in `.claude/skills/fantasy-football-edge/references/data-and-models.md`.
