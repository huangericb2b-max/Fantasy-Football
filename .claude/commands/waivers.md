---
description: Waiver wire targets ranked for this roster, with add/drop pairs
argument-hint: "[available players, comma-separated, or paste/screenshot the waiver list]"
allowed-tools: Bash(uv run ffedge:*), Bash(ffedge:*), Read, WebSearch, WebFetch
---

Find waiver adds for this roster. Available players given: $ARGUMENTS

1. Read `roster.toml` and `league.toml`. In a 6-team league the wire is deep, so only a real role change or a weekly starter is worth a move.
2. If no available list was given, ask Eric for one (League Tycoon screenshot or names). Until then, `uv run ffedge usage --risers --top 25` is a radar only; never call those players available.
3. For the candidates: `uv run ffedge usage --players "..." --weekly`, `uv run ffedge regression --players "..."`, `uv run ffedge project --players "..."`.
4. Check why each role grew (injury ahead of him, trade, benching) with a web search, and whether it lasts.
5. Rank by marginal value to this roster. For each: priority, add/drop pair, why, main risk, confidence. Dynasty league: weigh age and next-season role for stashes. Doing nothing is a valid answer.
