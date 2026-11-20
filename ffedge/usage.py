"""Weekly player usage: the opportunity numbers that drive fantasy points.

One row per player-week (regular season, offensive skill positions) with:
snap share, targets / target share, air yards share, WOPR, carries / rush share,
red-zone and inside-5 opportunities, league fantasy points, and ffverse
expected fantasy points (xFP) and expected TDs.
"""
from __future__ import annotations

import polars as pl

from . import data
from .scoring import add_league_points

SKILL = ["QB", "RB", "WR", "TE"]


def _pbp_opportunities(season: int) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    pbp = data.load("pbp", season).filter(
        (pl.col("season_type") == "REG") & pl.col("play_type").is_in(["pass", "run"])
    )
    rz = pl.col("yardline_100") <= 20
    i10 = pl.col("yardline_100") <= 10
    i5 = pl.col("yardline_100") <= 5
    tgt = (
        pbp.filter(pl.col("receiver_player_id").is_not_null())
        .group_by(["receiver_player_id", "week"])
        .agg(
            rz.sum().alias("rz_targets"),
            i10.sum().alias("i10_targets"),
            (pl.col("air_yards").fill_null(0) >= 20).sum().alias("deep_targets"),
        )
        .rename({"receiver_player_id": "player_id"})
    )
    car = (
        pbp.filter(pl.col("rusher_player_id").is_not_null() & (pl.col("play_type") == "run"))
        .group_by(["rusher_player_id", "week"])
        .agg(rz.sum().alias("rz_carries"), i5.sum().alias("i5_carries"))
        .rename({"rusher_player_id": "player_id"})
    )
    team = (
        pbp.group_by(["posteam", "week"])
        .agg(
            (pl.col("qb_dropback") == 1).sum().alias("team_dropbacks"),
            (rz & (pl.col("play_type") == "run")).sum().alias("team_rz_carries"),
            (rz & pl.col("receiver_player_id").is_not_null()).sum().alias("team_rz_targets"),
        )
        .rename({"posteam": "team"})
    )
    return tgt, car, team


def _snaps(season: int) -> pl.DataFrame:
    sn = data.load("snaps", season).filter(pl.col("game_type") == "REG")
    ids = data.players().select(["gsis_id", "pfr_id"]).drop_nulls().unique("pfr_id")
    return (
        sn.join(ids, left_on="pfr_player_id", right_on="pfr_id", how="inner")
        .select(
            pl.col("gsis_id").alias("player_id"),
            "week",
            pl.col("offense_snaps").alias("snaps"),
            pl.col("offense_pct").alias("snap_share"),
        )
        .unique(["player_id", "week"])
    )


def weekly_usage(season: int, scoring: dict) -> pl.DataFrame:
    st = data.load("player_stats", season).filter(
        (pl.col("season_type") == "REG") & pl.col("position").is_in(SKILL)
    )
    st = add_league_points(st, scoring)
    team_carries = (
        data.load("player_stats", season)
        .filter(pl.col("season_type") == "REG")
        .group_by(["team", "week"])
        .agg(pl.col("carries").fill_null(0).sum().alias("team_carries"))
    )
    tgt, car, team = _pbp_opportunities(season)
    opp = data.load("ff_opportunity", season).select(
        "player_id", pl.col("week").cast(pl.Int32),
        pl.col("total_fantasy_points_exp").alias("xfp"),
        pl.col("total_touchdown_exp").alias("xtd"),
        pl.col("total_touchdown").alias("td_opp"),
        pl.col("rec_yards_gained_exp").alias("x_rec_yds"),
        pl.col("receptions_exp").alias("x_rec"),
    )
    df = (
        st.select(
            "player_id", pl.col("player_display_name").alias("player"), "position", "team",
            pl.col("opponent_team").alias("opp"), "week", "fp",
            pl.col("fantasy_points_ppr").alias("fp_ppr"),
            "targets", "receptions", "receiving_yards", "receiving_air_yards", "target_share",
            "air_yards_share", "wopr", "carries", "rushing_yards", "attempts", "passing_yards",
            (pl.col("receiving_tds").fill_null(0) + pl.col("rushing_tds").fill_null(0)).alias("tds"),
            "passing_tds", "passing_epa", "rushing_epa", "receiving_epa",
        )
        .join(team_carries, on=["team", "week"], how="left")
        .join(tgt, on=["player_id", "week"], how="left")
        .join(car, on=["player_id", "week"], how="left")
        .join(team, on=["team", "week"], how="left")
        .join(_snaps(season), on=["player_id", "week"], how="left")
        .join(opp, on=["player_id", "week"], how="left")
        .with_columns(
            pl.when(pl.col("team_carries") > 0).then(pl.col("carries").fill_null(0) / pl.col("team_carries"))
            .otherwise(None).alias("rush_share"),
            pl.col(["rz_targets", "i10_targets", "deep_targets", "rz_carries", "i5_carries"]).fill_null(0),
        )
        .with_columns(
            pl.when((pl.col("team_rz_targets") + pl.col("team_rz_carries")) > 0)
            .then((pl.col("rz_targets") + pl.col("rz_carries"))
                  / (pl.col("team_rz_targets") + pl.col("team_rz_carries")))
            .otherwise(None).alias("rz_share"),
            pl.lit(season).alias("season"),
        )
        .sort(["player", "week"])
    )
    return df


def _window(df: pl.DataFrame, label: str) -> list[pl.Expr]:
    return [
        pl.len().alias(f"g_{label}"),
        pl.col("snap_share").mean().alias(f"snap_{label}"),
        pl.col("targets").mean().alias(f"tgt_{label}"),
        pl.col("target_share").mean().alias(f"tgt_sh_{label}"),
        pl.col("air_yards_share").mean().alias(f"ay_sh_{label}"),
        pl.col("carries").mean().alias(f"car_{label}"),
        pl.col("rush_share").mean().alias(f"rush_sh_{label}"),
        pl.col("rz_share").mean().alias(f"rz_sh_{label}"),
        pl.col("fp").mean().alias(f"fp_{label}"),
        pl.col("xfp").mean().alias(f"xfp_{label}"),
    ]


def summarize(weekly: pl.DataFrame, last_n: int = 4) -> pl.DataFrame:
    """Season vs. last-N-games usage per player, plus the change between them."""
    season = weekly.group_by(["player_id", "player", "position"]).agg(
        pl.col("team").last(), *_window(weekly, "szn"),
        pl.col("i5_carries").sum().alias("i5_carries_szn"),
        pl.col("rz_targets").sum().alias("rz_targets_szn"),
    )
    recent = (
        weekly.sort("week").group_by("player_id").tail(last_n)
        .group_by("player_id").agg(*_window(weekly, "recent"))
    )
    out = season.join(recent, on="player_id", how="left")
    return out.with_columns(
        (pl.col("tgt_sh_recent") - pl.col("tgt_sh_szn")).alias("tgt_sh_delta"),
        (pl.col("rush_sh_recent") - pl.col("rush_sh_szn")).alias("rush_sh_delta"),
        (pl.col("snap_recent") - pl.col("snap_szn")).alias("snap_delta"),
        (pl.col("xfp_recent") - pl.col("xfp_szn")).alias("xfp_delta"),
    )


def risers(summary: pl.DataFrame, min_games: int = 3, top: int = 20) -> pl.DataFrame:
    """Players whose expected-points role grew most in the recent window (waiver radar)."""
    return (
        summary.filter((pl.col("g_recent") >= min_games) & pl.col("position").is_in(["RB", "WR", "TE"])
                       & (pl.col("snap_recent") >= 0.35))
        .sort("xfp_delta", descending=True, nulls_last=True)
        .head(top)
    )


def find_players(weekly: pl.DataFrame, names: list[str]) -> tuple[list[str], list[str]]:
    """Match user-typed names to player_ids (case-insensitive, then substring)."""
    lookup = weekly.select("player_id", "player").unique()
    ids, missing = [], []
    for n in names:
        n0 = n.strip().lower()
        hit = lookup.filter(pl.col("player").str.to_lowercase() == n0)
        if hit.height == 0:
            hit = lookup.filter(pl.col("player").str.to_lowercase().str.contains(n0, literal=True))
        if hit.height == 0:
            missing.append(n)
        else:
            ids.extend(hit["player_id"].to_list()[:1])
    return ids, missing
