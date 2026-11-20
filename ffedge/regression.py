"""Over/under-performance vs. expected: where scoring may drift back toward role.

Expected values come from ffverse's expected-points model (ff_opportunity),
which prices every target and carry by down, distance, field position and air
yards. Its scoring is standard full PPR (4-pt pass TD), so comparisons here use
nflverse's `fantasy_points_ppr`, not league points.

A gap is a reason to look, not proof of a reversal. Check whether role, QB,
health or scheme changed before trusting the expected number.
"""
from __future__ import annotations

import polars as pl


def regression_table(weekly: pl.DataFrame, min_games: int = 4) -> pl.DataFrame:
    g = (
        weekly.filter(pl.col("xfp").is_not_null())
        .group_by(["player_id", "player", "position"])
        .agg(
            pl.col("team").last(),
            pl.len().alias("games"),
            pl.col("fp_ppr").sum().alias("fp"),
            pl.col("xfp").sum().alias("xfp"),
            pl.col("td_opp").sum().alias("td"),
            pl.col("xtd").sum().alias("xtd"),
            pl.col("receptions").fill_null(0).sum().alias("rec"),
            pl.col("x_rec").sum().alias("x_rec"),
            pl.col("receiving_yards").fill_null(0).sum().alias("rec_yds"),
            pl.col("x_rec_yds").sum().alias("x_rec_yds"),
        )
        .filter(pl.col("games") >= min_games)
        .with_columns(
            ((pl.col("fp") - pl.col("xfp")) / pl.col("games")).alias("fpoe_pg"),
            (pl.col("td") - pl.col("xtd")).alias("td_oe"),
            (pl.col("xfp") / pl.col("games")).alias("xfp_pg"),
            (pl.col("fp") / pl.col("games")).alias("fp_pg"),
            (pl.col("rec_yds") - pl.col("x_rec_yds")).alias("rec_yds_oe"),
        )
    )
    # Share of the over/under-performance explained by touchdowns (6 pts each).
    g = g.with_columns(
        pl.when((pl.col("fp") - pl.col("xfp")).abs() > 1)
        .then((pl.col("td_oe") * 6) / (pl.col("fp") - pl.col("xfp")))
        .otherwise(None)
        .clip(-2, 2)
        .alias("td_driven_frac")
    )
    return g.with_columns(_flag().alias("flag")).sort("fpoe_pg")


def _flag() -> pl.Expr:
    return (
        pl.when((pl.col("td_oe") >= 2.5) & (pl.col("td_driven_frac") > 0.6))
        .then(pl.lit("TD-driven overperformance: sell-high / fade candidate"))
        .when((pl.col("td_oe") <= -2.0) & (pl.col("xfp_pg") >= 10))
        .then(pl.lit("TD-unlucky with a real role: buy-low candidate"))
        .when(pl.col("fpoe_pg") >= 4)
        .then(pl.lit("Big overperformance: check efficiency is sustainable"))
        .when((pl.col("fpoe_pg") <= -3) & (pl.col("xfp_pg") >= 10))
        .then(pl.lit("Underperforming a strong role: buy-low candidate"))
        .otherwise(pl.lit(""))
    )


def buy_low(table: pl.DataFrame, top: int = 15) -> pl.DataFrame:
    return table.filter(pl.col("xfp_pg") >= 8).sort("fpoe_pg").head(top)


def sell_high(table: pl.DataFrame, top: int = 15) -> pl.DataFrame:
    return table.filter(pl.col("fp_pg") >= 8).sort("fpoe_pg", descending=True).head(top)
