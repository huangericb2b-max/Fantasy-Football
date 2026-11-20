---
description: Evaluate a dynasty trade offer using role, expected points, regression and age
argument-hint: "I give X, Y / I get Z"
allowed-tools: Bash(uv run ffedge:*), Bash(ffedge:*), Read, WebSearch, WebFetch
---

Evaluate this dynasty trade: $ARGUMENTS

1. Read `roster.toml` and `league.toml` (6 teams, full PPR, dynasty).
2. For every player: `uv run ffedge usage --players "..."`, `uv run ffedge regression --players "..."`, `uv run ffedge project --players "..."`.
3. Look up age, contract and team situation for next season on the web, plus a current dynasty value source (name it and date it).
4. Give a verdict (accept / counter / decline), the rest-of-season impact on Eric's lineup, the 2027+ impact, and a specific counter if it's close. Flag any player whose 2026 points lean on TD luck (sell-high) or who is underperforming his role (buy-low).
