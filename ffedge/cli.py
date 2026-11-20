"""Command line: `ffedge <command>`. Run `ffedge -h` for the list."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import polars as pl

from . import data, matchup, project, regression, usage, whiteboard
from .config import ROOT, load_league, load_roster

REPORTS = ROOT / "reports"


def _names(args) -> list[str]:
    names = []
    if getattr(args, "players", None):
        names += [n.strip() for n in args.players.split(",") if n.strip()]
    if getattr(args, "roster", False):
        names += load_roster()["players"]
    if getattr(args, "watchlist", False):
        names += load_roster()["watchlist"]
    return names


def _show(df: pl.DataFrame, cols: list[str] | None = None, rows: int = 40) -> None:
    if cols:
        df = df.select([c for c in cols if c in df.columns])
    num = [c for c, t in zip(df.columns, df.dtypes) if t.is_float()]
    df = df.with_columns([pl.col(c).round(3) for c in num])
    with pl.Config(tbl_rows=rows, tbl_cols=40, tbl_width_chars=260, fmt_str_lengths=40,
                   tbl_hide_dataframe_shape=True, tbl_hide_column_data_types=True):
        print(df)


def _save(text: str, name: str) -> Path:
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / name
    path.write_text(text)
    return path


def cmd_status(args):
    ctx = data.week_context(args.season)
    print(f"Season {ctx['season']}, week {ctx['week']}: {len(ctx['final'])} final, {len(ctx['upcoming'])} upcoming")
    for k, v in data.data_status(ctx["season"]).items():
        print(f"  {k:15s} through week {v}")
    cov = matchup.coverage_current()
    print(f"  scheme_overrides {cov.height} teams entered" + (f" (as of {cov['as_of'].max()})" if cov.height else ""))


def cmd_refresh(args):
    print("Refreshed:", ", ".join(data.refresh(args.season)))
    cmd_status(args)


def cmd_usage(args):
    lg = load_league()
    season = args.season or data.current_season()
    w = usage.weekly_usage(season, lg.scoring)
    s = usage.summarize(w, last_n=args.last)
    cols = ["player", "position", "team", "g_szn", "snap_szn", "snap_recent", "tgt_sh_szn", "tgt_sh_recent",
            "ay_sh_recent", "rush_sh_szn", "rush_sh_recent", "rz_sh_szn", "i5_carries_szn",
            "xfp_szn", "xfp_recent", "fp_szn", "fp_recent"]
    if args.risers:
        print(f"Biggest expected-points role growth, last {args.last} games vs season (waiver radar):")
        _show(usage.risers(s, top=args.top), cols + ["xfp_delta"])
        return
    names = _names(args)
    if names:
        ids, missing = usage.find_players(w, names)
        if missing:
            print("Not found:", ", ".join(missing))
        s = s.filter(pl.col("player_id").is_in(ids))
        if args.weekly:
            _show(w.filter(pl.col("player_id").is_in(ids)).sort(["player", "week"]),
                  ["player", "week", "opp", "snap_share", "targets", "target_share", "air_yards_share", "carries",
                   "rush_share", "rz_targets", "rz_carries", "i5_carries", "xfp", "fp"], rows=200)
            return
    if args.position:
        s = s.filter(pl.col("position") == args.position.upper())
    _show(s.sort("xfp_recent", descending=True, nulls_last=True).head(args.top), cols)


def cmd_regression(args):
    lg = load_league()
    season = args.season or data.current_season()
    t = regression.regression_table(usage.weekly_usage(season, lg.scoring), min_games=args.min_games)
    if args.position:
        t = t.filter(pl.col("position") == args.position.upper())
    cols = ["player", "position", "team", "games", "fp_pg", "xfp_pg", "fpoe_pg", "td", "xtd", "td_oe",
            "rec_yds_oe", "flag"]
    names = _names(args)
    if names:
        w = usage.weekly_usage(season, lg.scoring)
        ids, _ = usage.find_players(w, names)
        _show(t.filter(pl.col("player_id").is_in(ids)), cols)
        return
    print("BUY LOW (scoring below what the role usually produces):")
    _show(regression.buy_low(t, args.top), cols)
    print("\nSELL HIGH / FADE (scoring above role; check if efficiency is real):")
    _show(regression.sell_high(t, args.top), cols)


def cmd_whiteboard(args):
    names = _names(args)
    if not names:
        sys.exit("Give --players \"A, B\" or --roster (fill roster.toml first).")
    text = whiteboard.build(load_league(), names, args.season, args.week)
    ctx = data.week_context(args.season)
    path = _save(text, f"whiteboard_{ctx['season']}_wk{args.week or ctx['week']}.md")
    print(text)
    print(f"\n[saved to {path.relative_to(ROOT)}]")


def cmd_project(args):
    lg = load_league()
    ctx = data.week_context(args.season)
    week = args.week or ctx["week"]
    ids = None
    names = _names(args)
    if names:
        w = usage.weekly_usage(ctx["season"], lg.scoring)
        ids, missing = usage.find_players(w, names)
        if missing:
            print("Not found:", ", ".join(missing))
    p = project.project(lg.scoring, ctx["season"], week, ids)
    if args.position:
        p = p.filter(pl.col("position") == args.position.upper())
    print(f"Week {week} projections, {lg.name} scoring. 80% range = p10 to p90.")
    _show(p.head(args.top))


def cmd_backtest(args):
    lg = load_league()
    test = args.test or data.current_season() - 1
    train = list(range(test - 3, test))
    print(project.backtest(lg.scoring, train, test))


def cmd_train(args):
    lg = load_league()
    ctx = data.week_context()
    cur = ctx["season"]
    print(project.train_and_save(lg.scoring, list(range(cur - 4, cur + 1)), args.week or ctx["week"]))


def cmd_defense(args):
    lg = load_league()
    ctx = data.week_context(args.season)
    week = args.week or ctx["week"]
    off, de = matchup.team_profiles(ctx["season"], week)
    if args.offense:
        _show(off.sort("pass_epa_rk"), ["team", "games", "pass_epa", "pass_epa_rk", "rush_epa", "rush_epa_rk",
                                        "pressure_proxy", "pressure_allowed_rk", "sack_rate", "proe_neutral",
                                        "plays_pg", "play_action_rate", "screen_rate"])
        return
    if args.position:
        f = matchup.fantasy_points_allowed(ctx["season"], week, lg.scoring)
        _show(f.filter(pl.col("position") == args.position.upper()).sort("adj_fpa_rk"))
        return
    _show(de.sort("pass_epa_rk"), ["team", "games", "pass_epa", "pass_epa_rk", "rush_epa", "rush_epa_rk",
                                   "pressure_proxy", "pressure_rk", "sack_rate", "blitz_rate", "blitz_rk",
                                   "avg_rushers", "stacked_box_rate", "explosive_pass_rate"])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="ffedge", description="Fantasy football analysis engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.set_defaults(fn=fn)
        p.add_argument("--season", type=int)
        return p

    def who(p):
        p.add_argument("--players", help='comma-separated, e.g. "Ja\'Marr Chase, Bijan Robinson"')
        p.add_argument("--roster", action="store_true", help="use players in roster.toml")
        p.add_argument("--watchlist", action="store_true", help="use watchlist in roster.toml")

    add("status", cmd_status, "current week and how fresh each dataset is")
    add("refresh", cmd_refresh, "force re-download of current-season data")

    p = add("usage", cmd_usage, "snap/target/rush/red-zone shares and xFP, season vs recent")
    who(p)
    p.add_argument("--last", type=int, default=4)
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--position")
    p.add_argument("--risers", action="store_true", help="biggest recent role growth (waiver radar)")
    p.add_argument("--weekly", action="store_true", help="week-by-week rows for the named players")

    p = add("regression", cmd_regression, "points and TDs vs expected: buy-low / sell-high")
    who(p)
    p.add_argument("--position")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--min-games", type=int, default=4)

    p = add("whiteboard", cmd_whiteboard, "Scheme/Trends/X-factor data sheet per game")
    who(p)
    p.add_argument("--week", type=int)

    p = add("project", cmd_project, "next-week projections with 80% ranges")
    who(p)
    p.add_argument("--week", type=int)
    p.add_argument("--position")
    p.add_argument("--top", type=int, default=40)

    p = add("defense", cmd_defense, "team defense (or --offense) profiles and ranks")
    p.add_argument("--week", type=int)
    p.add_argument("--offense", action="store_true")
    p.add_argument("--position", help="points allowed to this position instead")

    p = sub.add_parser("backtest", help="test the projection model on a past season")
    p.set_defaults(fn=cmd_backtest)
    p.add_argument("--test", type=int)

    p = sub.add_parser("train", help="retrain the projection model now")
    p.set_defaults(fn=cmd_train)
    p.add_argument("--week", type=int)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
