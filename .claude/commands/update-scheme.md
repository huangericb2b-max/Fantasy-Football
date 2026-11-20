---
description: Fill data/scheme_overrides.csv with current-season man/zone and MOFO/MOFC rates from a web source
argument-hint: "[team abbreviations, or blank for all 32]"
allowed-tools: Read, Edit, WebSearch, WebFetch
---

Update current-season defensive coverage rates for: $ARGUMENTS (blank = all teams).

1. Search for the latest team coverage tables: Sharp Football Analysis "coverage schemes" / man vs zone and MOFO vs MOFC by team, then FantasyPoints or Fantasy Life if Sharp is blocked.
2. Write rates as 0-1 decimals into `data/scheme_overrides.csv` (columns: team,man_rate,zone_rate,mofc_rate,mofo_rate,blitz_rate,source,as_of). Use nflverse team abbreviations (LA for the Rams, LAC, JAX, WAS). Replace existing rows for the same team.
3. Only enter numbers you actually read on the page. Leave a column blank rather than guessing. Put the site name in `source` and the page's date (or today if undated, noted) in `as_of`.
4. Report which teams you filled, which you couldn't, and the source.
