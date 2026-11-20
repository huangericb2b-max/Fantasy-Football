"""Team offense/defense profiles for whiteboard matchup breakdowns.

Everything is computed from games *before* the target week, so a profile for
week 11 never includes week 11 results.

Data limits (2026):
- nflverse stopped publishing participation data after 2025, so 2026 has no
  per-play man/zone, MOFO/MOFC or charted pressure. Coverage for the current
  season comes from data/scheme_overrides.csv (filled from Sharp Football or
  similar, with a source and date). The 2025 participation numbers are shown as
  a labeled prior-season baseline.
- Pressure for 2026 uses a proxy: (sacks + QB hits) / dropbacks from pbp.
- Blitz rate, pass rushers and box counts come from FTN charting (free tier),
  which usually lags pbp by about a week.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from . import data
from .config import ROOT
from .scoring import add_league_points

OVERRIDES = ROOT / "data" / "scheme_overrides.csv"
MOFC = ["COVER_1", "COVER_3", "COVER_0"]
MOFO = ["COVER_2", "COVER_4", "COVER_6", "2_MAN", "COVER_9"]


def _plays(season: int, before_week: int) -> pl.DataFrame:
    pbp = data.load("pbp", season).filter(
        (pl.col("season_type") == "REG")
        & (pl.col("week") < before_week)
        & pl.col("play_type").is_in(["pass", "run"])
        & (pl.col("two_point_attempt").fill_null(0) == 0)
    )
    ftn = data.load("ftn", season).select(
        pl.col("nflverse_game_id").alias("game_id"),
        pl.col("nflverse_play_id").cast(pl.Float64).alias("play_id"),
        pl.col("n_blitzers").clip(0, 11), pl.col("n_pass_rushers").clip(0, 11),
        pl.col("n_defense_box").clip(0, 11), "is_play_action", "is_screen_pass", "is_motion",
    )
    return pbp.join(ftn, on=["game_id", "play_id"], how="left")


def _side_stats(p: pl.DataFrame, key: str) -> pl.DataFrame:
    db = pl.col("qb_dropback") == 1
    run = (pl.col("play_type") == "run") & (pl.col("qb_scramble").fill_null(0) == 0)
    neutral = pl.col("wp").is_between(0.2, 0.8) & (pl.col("qtr") <= 3)
    charted = db & pl.col("n_blitzers").is_not_null()
    return p.group_by(key).agg(
        pl.col("game_id").n_unique().alias("games"),
        db.sum().alias("dropbacks"),
        pl.col("epa").filter(db).mean().alias("pass_epa"),
        pl.col("success").filter(db).mean().alias("pass_sr"),
        pl.col("epa").filter(run).mean().alias("rush_epa"),
        pl.col("success").filter(run).mean().alias("rush_sr"),
        (pl.col("yards_gained").filter(run).sum() / run.sum()).alias("ypc"),
        (pl.col("sack").filter(db).sum() / db.sum()).alias("sack_rate"),
        ((pl.col("sack").fill_null(0) + pl.col("qb_hit").fill_null(0)).clip(0, 1).filter(db).sum()
         / db.sum()).alias("pressure_proxy"),
        (pl.col("sack").filter(db).sum() / pl.col("game_id").n_unique()).alias("sacks_pg"),
        ((pl.col("yards_gained") >= 20) & db).sum().truediv(db.sum()).alias("explosive_pass_rate"),
        (pl.col("n_blitzers").filter(charted) > 0).mean().alias("blitz_rate"),
        pl.col("n_pass_rushers").filter(charted).mean().alias("avg_rushers"),
        (pl.col("n_defense_box").filter(run & pl.col("n_defense_box").is_not_null()) >= 8).mean().alias("stacked_box_rate"),
        pl.col("pass_oe").filter(neutral).mean().alias("proe_neutral"),
        pl.col("is_play_action").filter(db).mean().alias("play_action_rate"),
        pl.col("is_screen_pass").filter(db).mean().alias("screen_rate"),
        (pl.len() / pl.col("game_id").n_unique()).alias("plays_pg"),
        pl.col("week").max().alias("through_week"),
        pl.col("n_blitzers").filter(charted).len().alias("charted_dropbacks"),
    )


def team_profiles(season: int, before_week: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(offense, defense) profiles with 1-32 ranks.

    Defense ranks: 1 = best defense (lowest EPA allowed, most pressure).
    Offense ranks: 1 = best offense (highest EPA, least pressure allowed).
    """
    p = _plays(season, before_week)
    off = _side_stats(p, "posteam").rename({"posteam": "team"})
    de = _side_stats(p, "defteam").rename({"defteam": "team"})
    off = off.with_columns(
        pl.col("pass_epa").rank("ordinal", descending=True).alias("pass_epa_rk"),
        pl.col("rush_epa").rank("ordinal", descending=True).alias("rush_epa_rk"),
        pl.col("pressure_proxy").rank("ordinal").alias("pressure_allowed_rk"),
        pl.col("sack_rate").rank("ordinal").alias("sack_rate_rk"),
        pl.col("proe_neutral").rank("ordinal", descending=True).alias("proe_rk"),
    )
    de = de.with_columns(
        pl.col("pass_epa").rank("ordinal").alias("pass_epa_rk"),
        pl.col("rush_epa").rank("ordinal").alias("rush_epa_rk"),
        pl.col("pressure_proxy").rank("ordinal", descending=True).alias("pressure_rk"),
        pl.col("sack_rate").rank("ordinal", descending=True).alias("sack_rate_rk"),
        pl.col("blitz_rate").rank("ordinal", descending=True).alias("blitz_rk"),
    )
    return off, de


def fantasy_points_allowed(season: int, before_week: int, scoring: dict) -> pl.DataFrame:
    """Points allowed by position, raw and adjusted.

    adj_fpa = average of (player's points vs. this defense - that player's
    season average). Positive = defense gives up more than its opponents
    usually score. Rank 1 = most generous (best matchup).
    """
    st = data.load("player_stats", season).filter(
        (pl.col("season_type") == "REG") & (pl.col("week") < before_week)
        & pl.col("position").is_in(["QB", "RB", "WR", "TE"])
    )
    st = add_league_points(st, scoring)
    avg = st.group_by("player_id").agg(pl.col("fp").mean().alias("avg_fp"), pl.len().alias("n"))
    st = st.join(avg, on="player_id").with_columns(
        pl.when(pl.col("n") >= 3).then(pl.col("fp") - pl.col("avg_fp")).otherwise(None).alias("over_avg")
    )
    per_game = st.group_by(["opponent_team", "position", "week"]).agg(
        pl.col("fp").sum().alias("fp"), pl.col("over_avg").sum().alias("over_avg")
    )
    out = per_game.group_by(["opponent_team", "position"]).agg(
        pl.col("fp").mean().alias("fpa"), pl.col("over_avg").mean().alias("adj_fpa"),
        pl.len().alias("games"),
    ).rename({"opponent_team": "team"})
    return out.with_columns(
        pl.col("adj_fpa").rank("ordinal", descending=True).over("position").alias("adj_fpa_rk"),
        pl.col("fpa").rank("ordinal", descending=True).over("position").alias("fpa_rk"),
    )


def coverage_baseline(season: int) -> pl.DataFrame:
    """Man/zone and MOFO/MOFC rates by defense from participation data (<=2025)."""
    pa = data.load("participation", season)
    if pa.height == 0:
        return pl.DataFrame()
    cov = pa.filter(pl.col("defense_coverage_type").is_not_null() & (pl.col("defense_man_zone_type") != ""))
    pbp = data.load("pbp", season).select(
        pl.col("game_id").alias("nflverse_game_id"), pl.col("play_id").cast(pl.Int32), "defteam"
    )
    cov = cov.with_columns(pl.col("play_id").cast(pl.Int32)).join(pbp, on=["nflverse_game_id", "play_id"], how="inner")
    return cov.group_by("defteam").agg(
        (pl.col("defense_man_zone_type") == "MAN_COVERAGE").mean().alias("man_rate"),
        (pl.col("defense_man_zone_type") == "ZONE_COVERAGE").mean().alias("zone_rate"),
        pl.col("defense_coverage_type").is_in(MOFC).mean().alias("mofc_rate"),
        pl.col("defense_coverage_type").is_in(MOFO).mean().alias("mofo_rate"),
        pl.col("defense_coverage_type").mode().first().alias("top_coverage"),
        pl.col("was_pressure").mean().alias("charted_pressure_rate"),
        pl.len().alias("plays"),
    ).rename({"defteam": "team"}).with_columns(pl.lit(f"{season} participation (nflverse/FTN)").alias("source"))


def coverage_current(path: Path = OVERRIDES) -> pl.DataFrame:
    """Current-season coverage you or Claude entered from a dated public source."""
    if not path.exists():
        return pl.DataFrame()
    df = pl.read_csv(path, comment_prefix="#")
    return df


def receiver_coverage_splits(season: int) -> pl.DataFrame:
    """Per receiver: share of team targets and yards/target vs. man vs. zone.

    From participation data, so only seasons <= 2025. Without route data these
    are target shares per dropback, not TPRR; treat as a lean, not a split.
    """
    pa = data.load("participation", season)
    if pa.height == 0:
        return pl.DataFrame()
    pa = pa.select(
        "nflverse_game_id", pl.col("play_id").cast(pl.Int32), "defense_man_zone_type"
    ).filter(pl.col("defense_man_zone_type").is_in(["MAN_COVERAGE", "ZONE_COVERAGE"]))
    pbp = data.load("pbp", season).filter(pl.col("qb_dropback") == 1).select(
        pl.col("game_id").alias("nflverse_game_id"), pl.col("play_id").cast(pl.Int32),
        "posteam", "receiver_player_id", "receiver_player_name", "yards_gained", "pass_attempt",
    )
    j = pbp.join(pa, on=["nflverse_game_id", "play_id"], how="inner")
    team_db = j.group_by(["posteam", "defense_man_zone_type"]).agg(pl.len().alias("team_db"))
    rec = (
        j.filter(pl.col("receiver_player_id").is_not_null())
        .group_by(["receiver_player_id", "receiver_player_name", "posteam", "defense_man_zone_type"])
        .agg(pl.len().alias("targets"), pl.col("yards_gained").mean().alias("ypt"))
        .join(team_db, on=["posteam", "defense_man_zone_type"])
        .with_columns((pl.col("targets") / pl.col("team_db")).alias("tgt_per_db"))
    )
    wide = rec.pivot(
        on="defense_man_zone_type", index=["receiver_player_id", "receiver_player_name", "posteam"],
        values=["targets", "tgt_per_db", "ypt"],
    )
    return wide.rename({"receiver_player_id": "player_id"})


def implied_totals(season: int, week: int) -> pl.DataFrame:
    """Implied points per team from the closing spread/total in nflverse schedules.

    spread_line is the home team's expected margin (positive = home favored).
    """
    sch = data.load("schedules", season).filter((pl.col("week") == week) & (pl.col("game_type") == "REG"))
    rows = []
    for r in sch.iter_rows(named=True):
        tot, spr = r["total_line"], r["spread_line"]
        if tot is None or spr is None:
            continue
        home = (tot + spr) / 2
        rows.append({"team": r["home_team"], "implied": home, "game_id": r["game_id"]})
        rows.append({"team": r["away_team"], "implied": tot - home, "game_id": r["game_id"]})
    return pl.DataFrame(rows)
