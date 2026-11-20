---
description: Max Loeb-style whiteboard breakdown (Scheme / Trends / X-factors / Verdict) for every game with a player you're considering
argument-hint: "[player names, comma-separated] (blank = roster.toml)"
allowed-tools: Bash(uv run ffedge:*), Bash(ffedge:*), Read, Edit, WebSearch, WebFetch
---

Build a whiteboard game breakdown for: $ARGUMENTS (if blank, use `--roster`).

1. Run `uv run ffedge status`. Note the week, which games are final, and how far each dataset runs.
2. Run `uv run ffedge whiteboard --players "$ARGUMENTS"` (or `--roster`). Read the whole sheet.
3. For every defense in the sheet that shows "coverage not entered", search for current-season coverage rates (Sharp Football coverage tables first, then FantasyPoints or Fantasy Life man/zone articles). Add what you find to `data/scheme_overrides.csv` with the source and date, then rerun step 2. If you can't find a team, say so once and use the 2025 baseline, labeled.
4. Check news the data can't have: Wednesday-Friday practice reports, game statuses, QB changes, returning teammates. Use team sites, NFL.com, or beat reporters, and cite them.
5. Write the breakdown:
   - Lineup table at the top (legal lineup from `league.toml` slots if the full roster is known; otherwise just the players asked about), with projection and 80% range from the sheet.
   - One heading per game: "Away @ Home (line)".
   - Scheme: what the defense's shell gives up and how this player wins against it (alignment, route profile, 2025 man/zone lean if shown).
   - Trends: 3-5 numbers set against each other (pressure allowed vs generated, EPA ranks, adj points allowed to the position, implied total).
   - Verdict: start or sit for each player with the one decisive reason.
   - X-factors for the week at the end, 1-3 per game that matters.
6. Finish with what news would flip the closest call. Keep it phone-length. No em dashes.
