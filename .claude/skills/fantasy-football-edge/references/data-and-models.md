# Data and models reference

## Sources (all free, via nflreadpy)

| Dataset | Used for | Lag | Notes |
|---|---|---|---|
| Play-by-play (nflverse) | EPA, success rate, pressure proxy, PROE, red-zone/inside-5 opportunities, explosive plays | Usually next morning | EPA is real-football value, not fantasy points |
| Player stats (nflverse) | Weekly box scores, target share, air-yards share, WOPR, league fantasy points | Next morning | `ffedge` rescores with `league.toml` |
| Snap counts (PFR via nflverse) | Snap share | 1-2 days | Joined to player IDs through `load_players()` pfr_id |
| ff_opportunity (ffverse) | xFP, expected TDs, receptions and yards | 1-2 days | Standard full PPR, 4-pt pass TD |
| FTN charting (free) | Blitzers, pass rushers, box count, play action, screens | About a week | Blitz = 1+ blitzer per FTN's definition; runs higher than PFF's |
| Participation (nflverse/FTN/NGS) | Man/zone, coverage shell, charted pressure, time to throw | **Ends with 2025** | Prior-season baseline only |
| Injuries (nflverse) | Practice participation and game status | Daily during the week | Verify late-week statuses on team sites |
| Schedules (nflverse) | Spread, total, kickoff, final scores | Lines update during the week | `spread_line` = home expected margin |

Always check the actual latest week in the rows (`ffedge status`), not a site timestamp.

## Definitions

- **Pressure proxy (2026)**: plays with a sack or QB hit / dropbacks. Runs well below charted pressure: in 2025 the proxy ranged about 9-22% by defense while FTN-charted pressure ranged 21-35%. Compare teams with each other, not with PFF or charted numbers.
- **Neutral PROE**: mean `pass_oe` with win probability 20-80% in quarters 1-3. Positive = passes more than the situation predicts.
- **Adj FPA**: for each game, opponents' points minus those players' season averages (players with 3+ games), averaged across games. Positive = defense gives up more than its opponents usually score. Rank 1 = best matchup.
- **xFP / FPOE**: ffverse prices each target and carry by field position, down, distance and air yards. FPOE = actual PPR points minus xFP. Large positive FPOE built mostly on TD over-expectation (`td_driven_frac` > 0.6) is the classic regression candidate; large negative FPOE with a strong role (xFP/g 10+) is the buy-low.
- **MOFC / MOFO**: in the 2025 baseline, MOFC = Cover 0, 1, 3; MOFO = Cover 2, 4, 6, 9, 2-Man.
- **Man/zone lean (2025)**: a receiver's targets per team dropback against man vs. zone, with yards per target. It's a share of dropbacks, not TPRR, because route data isn't joined. Small samples (under ~20 targets) are noise.

## Projection model

- HistGradientBoosting (scikit-learn): mean model plus quantile models for the 80% range.
- Trained on the four prior seasons plus the current season's completed weeks; retrains automatically when the week or scoring changes.
- Features (all from games before the target week): last-3 and season league points, last-3 and season xFP, snap share, target and rush share, red-zone share, games played, position, opponent points allowed to the position vs league average, team implied total, home.
- 2025 backtest (trained 2022-2024): MAE 4.50 vs 4.52 for season average and 4.51 for season xFP; Spearman rank correlation 0.688 vs 0.665 for season average; 81% of outcomes inside the 80% range.
- What that means: weekly fantasy scoring is mostly noise, and no public model is far better than a smart average. The model helps most with ranking close players and with players whose role just changed. It can't see this week's injuries, depth chart news, weather or coaching changes. Adjust for those in words; don't pretend the number already includes them.
- Run `ffedge backtest` after changing features. Don't add a feature that leaks the target week.

## Rules

- Separate observed stats, model outputs, web sources and judgment.
- Name the creator of any metric (ffverse xFP, FTN charting, Sharp Football coverage tables).
- If a source is blocked or missing, say so once and work from what you have.
- Don't present scenario guesses as calibrated percentiles; only the model's range is calibrated, and only loosely.
