"""Whiteboard data sheet: Scheme / Trends / X-factor numbers per game.

This builds the evidence, not the verdict. The /whiteboard command has Claude
read this sheet, add web-sourced coverage and news, and write the start/sit calls.
"""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl

from . import data, matchup, project, regression, usage
from .config import League


def _bad(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _pct(x, d=0) -> str:
    return "n/a" if _bad(x) else f"{x * 100:.{d}f}%"


def _num(x, d=2, signed=False) -> str:
    if _bad(x):
        return "n/a"
    return f"{x:+.{d}f}" if signed else f"{x:.{d}f}"


def _row(df: pl.DataFrame, **kw) -> dict:
    f = df
    for k, v in kw.items():
        f = f.filter(pl.col(k) == v)
    return f.row(0, named=True) if f.height else {}


def _spread_text(g: dict) -> str:
    s, t = g.get("spread_line"), g.get("total_line")
    if s is None:
        return "line n/a"
    fav = g["home_team"] if s > 0 else g["away_team"]
    side = f"{fav} -{abs(s):g}" if s != 0 else "PK"
    return f"{side}, O/U {t:g}" if t is not None else side


def _injuries(season: int, week: int, teams: list[str]) -> pl.DataFrame:
    inj = data.load("injuries", season)
    inj = inj.filter((pl.col("week") == week) & pl.col("team").is_in(teams))
    keep = pl.col("report_status").is_in(["Out", "Doubtful", "Questionable"]) | pl.col("practice_status").str.contains("Did Not")
    return inj.filter(keep & pl.col("position").is_in(["QB", "RB", "WR", "TE", "T", "G", "C", "CB", "S", "LB", "DE", "DT", "OLB", "ILB", "FS", "SS"]))


def build(league: League, names: list[str], season: int | None = None, week: int | None = None) -> str:
    ctx = data.week_context(season)
    season = ctx["season"]
    week = week or ctx["week"]
    tz = ZoneInfo(league.timezone)
    now = datetime.now(tz).strftime("%a %b %d %Y, %I:%M %p %Z")

    weekly = usage.weekly_usage(season, league.scoring)
    weekly_prior = weekly.filter(pl.col("week") < week)
    ids, missing = usage.find_players(weekly_prior, names)
    summ = usage.summarize(weekly_prior)
    reg = regression.regression_table(weekly_prior, min_games=3)
    off, de = matchup.team_profiles(season, week)
    fpa = matchup.fantasy_points_allowed(season, week, league.scoring)
    cov_now = matchup.coverage_current()
    cov_prev = matchup.coverage_baseline(season - 1)
    splits = matchup.receiver_coverage_splits(season - 1)
    try:
        proj = project.project(league.scoring, season, week, ids)
    except Exception as e:  # model training needs several seasons of data
        proj = pl.DataFrame()
        print(f"[projection skipped: {e}]")

    sch = data.load("schedules", season).filter((pl.col("week") == week) & (pl.col("game_type") == "REG"))
    status = data.data_status(season)

    players = summ.filter(pl.col("player_id").is_in(ids))
    by_game: dict[str, list[dict]] = {}
    bye = []
    for p in players.iter_rows(named=True):
        g = sch.filter((pl.col("home_team") == p["team"]) | (pl.col("away_team") == p["team"]))
        if g.height == 0:
            bye.append(p["player"])
            continue
        by_game.setdefault(g["game_id"][0], []).append(p)

    out = [f"# Whiteboard data sheet: {season} week {week}", "",
           f"As of {now}. Data through: " + ", ".join(f"{k} wk {v}" for k, v in status.items()) + ".",
           "Ranks are 1-32 among teams. Defense rank 1 = toughest; offense rank 1 = best; "
           "Adj FPA rank 1 = most generous to the position.", ""]
    if missing:
        out.append(f"**Not found in {season} stats:** {', '.join(missing)} (check spelling or rookie/no snaps).\n")
    if bye:
        out.append(f"**On bye / no game week {week}:** {', '.join(bye)}\n")
    if proj.height:
        out += ["## Projections (league scoring, model)", "",
                "| Player | Pos | Opp | Proj | 80% range | Last 3 | Season | xFP/g |",
                "|---|---|---|---|---|---|---|---|"]
        for r in proj.iter_rows(named=True):
            opp = ("vs " if r["home"] else "@ ") + r["opp"]
            out.append(f"| {r['player']} | {r['position']} | {opp} | {r['proj']} | {r['p10']}-{r['p90']} | "
                       f"{_num(r['fp_l3'], 1)} | {_num(r['fp_szn'], 1)} | {_num(r['xfp_szn'], 1)} |")
        out.append("\nModel backtest (2025): MAE about 4.5 pts vs 4.52 for season average. "
                   "It ranks players a bit better than averages; it does not see injuries or news.\n")

    for gid, plist in sorted(by_game.items(), key=lambda kv: sch.filter(pl.col("game_id") == kv[0])["gameday"][0]):
        g = _row(sch, game_id=gid)
        final = g.get("home_score") is not None
        out.append(f"## {g['away_team']} @ {g['home_team']} ({_spread_text(g)})")
        out.append(f"{g['gameday']} {g['gametime']} ET" + (f" | FINAL {g['away_score']}-{g['home_score']}" if final else ""))
        out.append("")
        teams = [g["away_team"], g["home_team"]]
        for team in teams:
            side = [p for p in plist if p["team"] == team]
            if not side:
                continue
            opp = teams[1] if team == teams[0] else teams[0]
            o, d = _row(off, team=team), _row(de, team=opp)
            out.append(f"### {team} offense vs {opp} defense")
            out.append("")
            for p in side:
                out.append(f"**{p['player']} ({p['position']})**")
                out.append(
                    f"- Role (season / last {p['g_recent']}): snaps {_pct(p['snap_szn'])} / {_pct(p['snap_recent'])}; "
                    f"target share {_pct(p['tgt_sh_szn'])} / {_pct(p['tgt_sh_recent'])}; "
                    f"rush share {_pct(p['rush_sh_szn'])} / {_pct(p['rush_sh_recent'])}; "
                    f"RZ share {_pct(p['rz_sh_szn'])}; xFP/g {_num(p['xfp_szn'], 1)} / {_num(p['xfp_recent'], 1)}; "
                    f"pts/g {_num(p['fp_szn'], 1)} / {_num(p['fp_recent'], 1)} ({p['g_szn']} games)"
                )
                r = _row(reg, player_id=p["player_id"])
                if r:
                    out.append(f"- Regression: {_num(r['fpoe_pg'], 1, signed=True)} pts/g vs expected; "
                               f"TDs {r['td']:.0f} vs {r['xtd']:.1f} expected."
                               + (f" Flag: {r['flag']}" if r["flag"] else ""))
                if p["position"] in ("WR", "TE") and splits.height:
                    s_ = _row(splits, player_id=p["player_id"])
                    if s_ and s_.get("targets_MAN_COVERAGE") and s_.get("targets_ZONE_COVERAGE"):
                        out.append(
                            f"- {season - 1} man/zone lean: tgt/dropback vs man {_pct(s_['tgt_per_db_MAN_COVERAGE'], 1)} "
                            f"({s_['targets_MAN_COVERAGE']} tgts, {_num(s_['ypt_MAN_COVERAGE'], 1)} Y/T) vs zone "
                            f"{_pct(s_['tgt_per_db_ZONE_COVERAGE'], 1)} ({s_['targets_ZONE_COVERAGE']} tgts, "
                            f"{_num(s_['ypt_ZONE_COVERAGE'], 1)} Y/T)"
                        )
                out.append("")
            # Scheme (opposing defense)
            cn = _row(cov_now, team=opp) if cov_now.height else {}
            cp = _row(cov_prev, team=opp) if cov_prev.height else {}
            if cn:
                out.append(f"- **Scheme {season}:** man {_pct(cn.get('man_rate'))}, zone {_pct(cn.get('zone_rate'))}, "
                           f"MOFC {_pct(cn.get('mofc_rate'))}, MOFO {_pct(cn.get('mofo_rate'))} "
                           f"({cn.get('source')}, {cn.get('as_of')})")
            else:
                out.append(f"- **Scheme {season}:** coverage not entered for {opp} (add to data/scheme_overrides.csv)")
            out.append(f"- **Pressure look:** blitz {_pct(d.get('blitz_rate'))} (rk {d.get('blitz_rk')}, FTN through wk "
                       f"{status.get('ftn')}), avg rushers {_num(d.get('avg_rushers'), 1)}")
            if cp:
                out.append(f"- **{season - 1} baseline:** man {_pct(cp['man_rate'])}, MOFC {_pct(cp['mofc_rate'])}, "
                           f"MOFO {_pct(cp['mofo_rate'])}, top shell {cp['top_coverage']}, charted pressure "
                           f"{_pct(cp['charted_pressure_rate'])}")
            if any(p["position"] == "RB" for p in side):
                out.append(f"- **Run D:** rush EPA rk {d.get('rush_epa_rk')}, {_num(d.get('ypc'), 1)} YPC allowed, "
                           f"8+ man box {_pct(d.get('stacked_box_rate'))}")
            out += ["", f"| Trend | {team} offense | {opp} defense |", "|---|---|---|",
                    f"| Pass EPA/play | {_num(o.get('pass_epa'))} (rk {o.get('pass_epa_rk')}) | {_num(d.get('pass_epa'))} allowed (rk {d.get('pass_epa_rk')}) |",
                    f"| Rush EPA/play | {_num(o.get('rush_epa'))} (rk {o.get('rush_epa_rk')}) | {_num(d.get('rush_epa'))} allowed (rk {d.get('rush_epa_rk')}) |",
                    f"| Pressure proxy (sack+hit / dropback) | {_pct(o.get('pressure_proxy'), 1)} allowed (rk {o.get('pressure_allowed_rk')}) | {_pct(d.get('pressure_proxy'), 1)} generated (rk {d.get('pressure_rk')}) |",
                    f"| Sacks/game | {_num(o.get('sacks_pg'), 1)} taken | {_num(d.get('sacks_pg'), 1)} made |",
                    f"| Explosive pass rate (20+) | {_pct(o.get('explosive_pass_rate'), 1)} | {_pct(d.get('explosive_pass_rate'), 1)} allowed |",
                    f"| Neutral PROE / plays per game | {_num(o.get('proe_neutral'), 1, signed=True)}% / {_num(o.get('plays_pg'), 1)} | |"]
            for pos in sorted({p["position"] for p in side}):
                f_ = _row(fpa, team=opp, position=pos)
                out.append(f"| {pos} pts allowed/g (adj vs avg, rk) | | {_num(f_.get('fpa'), 1)} "
                           f"({_num(f_.get('adj_fpa'), 1, signed=True)}, rk {f_.get('adj_fpa_rk')}) |")
            out.append("")
        inj = _injuries(season, week, teams)
        if inj.height:
            out.append("**Injury report (X-factor candidates):**")
            for r in inj.sort(["team", "report_status"]).iter_rows(named=True):
                out.append(f"- {r['team']} {r['position']} {r['full_name']}: {r['report_status'] or 'no game status'}"
                           f" ({r['report_primary_injury'] or r['practice_primary_injury'] or 'n/a'}; practice: {r['practice_status'] or 'n/a'})")
        else:
            out.append(f"**Injury report:** nothing in nflverse for week {week} yet; check team reports.")
        out += ["", "**Verdict:** _(Claude: start/sit + one decisive reason per player)_", "", "---", ""]
    return "\n".join(out)
