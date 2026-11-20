"""League-specific fantasy points from nflverse player_stats rows."""
from __future__ import annotations

import polars as pl


def fantasy_points_expr(s: dict) -> pl.Expr:
    c = lambda name: pl.col(name).fill_null(0)  # noqa: E731
    return (
        c("receptions") * s["reception"]
        + c("receiving_yards") * s["rec_yard"]
        + c("receiving_tds") * s["rec_td"]
        + c("rushing_yards") * s["rush_yard"]
        + c("rushing_tds") * s["rush_td"]
        + c("passing_yards") * s["pass_yard"]
        + c("passing_tds") * s["pass_td"]
        + c("passing_interceptions") * s["interception"]
        + (c("rushing_fumbles_lost") + c("receiving_fumbles_lost") + c("sack_fumbles_lost")) * s["fumble_lost"]
        + (c("passing_2pt_conversions") + c("rushing_2pt_conversions") + c("receiving_2pt_conversions")) * s["two_point"]
    )


def add_league_points(stats: pl.DataFrame, scoring: dict) -> pl.DataFrame:
    return stats.with_columns(fantasy_points_expr(scoring).round(2).alias("fp"))
