---
description: Build the visual matchup cards (usage charts, target/run maps, defense zone maps, coverage, rank edges) and open them
argument-hint: "[player names, comma-separated] (blank = roster.toml)"
allowed-tools: Bash(uv run ffedge:*), Bash(ffedge:*), Read, Edit, WebSearch, WebFetch
---

Build matchup cards for: $ARGUMENTS (blank = `--roster`).

1. Run `uv run ffedge status`. If `scheme_overrides 0 teams entered`, offer to run `/update-scheme` first so the coverage bars show this season instead of the 2025 baseline.
2. Run `uv run ffedge graphic --players "$ARGUMENTS"` (or `--roster`). It saves `reports/cards_<season>_wk<week>.html` and opens it in the browser.
3. In chat, give a short read of what the cards show for each player: one line on role trend, one on the zone matchup (where he gets the ball vs where the defense is soft or tough), and anything that looks off (tiny samples, a role that just changed). No em dashes.
