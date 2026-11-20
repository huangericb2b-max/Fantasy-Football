"""Next-week fantasy point projections with 10th/50th/90th percentile ranges.

Model: gradient-boosted trees (scikit-learn HistGradientBoosting) trained on
player-weeks from past seasons. Every feature uses only games before the target
week, so the backtest is honest about what was knowable at kickoff.

Features: recent and season league points, ffverse expected points (xFP),
snap/target/rush/red-zone shares, games played, position, opponent's points
allowed to the position (prior weeks, vs. league average), the team's implied
total from the betting line, and home/away.

Limits: it projects players who play. It knows nothing about this week's
injuries, depth-chart news or weather; Claude layers those on top.
"""
from __future__ import annotations

import pickle

import numpy as np
import polars as pl
from sklearn.ensemble import HistGradientBoostingRegressor

from . import data
from .config import ROOT
from .usage import weekly_usage

MODEL_PATH = ROOT / "data" / "models" / "projection.pkl"
POS = ["QB", "RB", "WR", "TE"]
FEATURES = [
    "fp_l3", "fp_szn", "xfp_l3", "xfp_szn", "snap_l3", "tgt_sh_l3", "tgt_sh_szn",
    "rush_sh_l3", "rush_sh_szn", "rz_sh_szn", "games_prior", "opp_fpa_vs_avg",
    "implied", "home", "pos_QB", "pos_RB", "pos_WR", "pos_TE",
]
QUANTILES = {"p10": 0.085, "p50": 0.5, "p90": 0.915}  # widened so ~80% of 2025 outcomes land inside p10-p90


def _roll(col: str, n: int | None, alias: str) -> pl.Expr:
    shifted = pl.col(col).shift(1)
    expr = shifted.rolling_mean(n, min_samples=1) if n else shifted.cum_sum() / shifted.cum_count()
    return expr.over(["player_id", "season"]).alias(alias)


def _opp_fpa(season: int, weekly: pl.DataFrame) -> pl.DataFrame:
    """Opponent's points allowed to a position in prior weeks, minus league average."""
    g = weekly.group_by(["opp", "position", "week"]).agg(pl.col("fp").sum().alias("fpa")).sort("week")
    g = g.with_columns(
        (pl.col("fpa").cum_sum().shift(1) / pl.col("fpa").cum_count().shift(1))
        .over(["opp", "position"]).alias("opp_fpa_prior")
    )
    lg = g.group_by(["position", "week"]).agg(pl.col("opp_fpa_prior").mean().alias("lg_avg"))
    return g.join(lg, on=["position", "week"]).with_columns(
        (pl.col("opp_fpa_prior") - pl.col("lg_avg")).alias("opp_fpa_vs_avg")
    ).select("opp", "position", "week", "opp_fpa_vs_avg")


def _implied(season: int) -> pl.DataFrame:
    sch = data.load("schedules", season).filter(pl.col("game_type") == "REG")
    home = sch.select(
        pl.col("home_team").alias("team"), "week",
        ((pl.col("total_line") + pl.col("spread_line")) / 2).alias("implied"), pl.lit(1).alias("home"),
        pl.col("away_team").alias("opp"),
    )
    away = sch.select(
        pl.col("away_team").alias("team"), "week",
        ((pl.col("total_line") - pl.col("spread_line")) / 2).alias("implied"), pl.lit(0).alias("home"),
        pl.col("home_team").alias("opp"),
    )
    return pl.concat([home, away]).with_columns(pl.col("week").cast(pl.Int32))


def build_features(season: int, scoring: dict) -> pl.DataFrame:
    """One row per player-week with pre-game features and the actual result (fp)."""
    w = weekly_usage(season, scoring).sort(["player_id", "week"])
    w = w.with_columns(
        _roll("fp", 3, "fp_l3"), _roll("fp", None, "fp_szn"),
        _roll("xfp", 3, "xfp_l3"), _roll("xfp", None, "xfp_szn"),
        _roll("snap_share", 3, "snap_l3"),
        _roll("target_share", 3, "tgt_sh_l3"), _roll("target_share", None, "tgt_sh_szn"),
        _roll("rush_share", 3, "rush_sh_l3"), _roll("rush_share", None, "rush_sh_szn"),
        _roll("rz_share", None, "rz_sh_szn"),
        pl.col("week").cum_count().over(["player_id", "season"]).sub(1).alias("games_prior"),
    )
    w = w.join(_opp_fpa(season, w), on=["opp", "position", "week"], how="left")
    w = w.join(_implied(season).drop("opp"), on=["team", "week"], how="left")
    w = w.with_columns([(pl.col("position") == p).cast(pl.Int8).alias(f"pos_{p}") for p in POS])
    return w


def upcoming_rows(season: int, week: int, scoring: dict) -> pl.DataFrame:
    """Feature rows for a week that hasn't been played, from all prior games."""
    w = weekly_usage(season, scoring).filter(pl.col("week") < week).sort(["player_id", "week"])
    agg = w.group_by(["player_id", "player", "position"]).agg(
        pl.col("team").last(),
        pl.col("fp").tail(3).mean().alias("fp_l3"), pl.col("fp").mean().alias("fp_szn"),
        pl.col("xfp").tail(3).mean().alias("xfp_l3"), pl.col("xfp").mean().alias("xfp_szn"),
        pl.col("snap_share").tail(3).mean().alias("snap_l3"),
        pl.col("target_share").tail(3).mean().alias("tgt_sh_l3"), pl.col("target_share").mean().alias("tgt_sh_szn"),
        pl.col("rush_share").tail(3).mean().alias("rush_sh_l3"), pl.col("rush_share").mean().alias("rush_sh_szn"),
        pl.col("rz_share").mean().alias("rz_sh_szn"),
        pl.len().alias("games_prior"),
    )
    imp = _implied(season).filter(pl.col("week") == week)
    agg = agg.join(imp, on="team", how="inner").with_columns(pl.lit(week).cast(pl.Int32).alias("week"))
    # Opponent points allowed to position through last week, vs league average.
    g = w.group_by(["opp", "position", "week"]).agg(pl.col("fp").sum().alias("fpa"))
    o = g.group_by(["opp", "position"]).agg(pl.col("fpa").mean().alias("opp_fpa"))
    o = o.with_columns((pl.col("opp_fpa") - pl.col("opp_fpa").mean().over("position")).alias("opp_fpa_vs_avg"))
    agg = agg.join(o.select("opp", "position", "opp_fpa_vs_avg"), on=["opp", "position"], how="left")
    return agg.with_columns([(pl.col("position") == p).cast(pl.Int8).alias(f"pos_{p}") for p in POS])


def _xy(df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    df = df.filter(pl.col("games_prior") >= 2)
    X = df.select(FEATURES).cast(pl.Float64).to_numpy()
    y = df["fp"].cast(pl.Float64).to_numpy()
    return X, y


def _fit(X: np.ndarray, y: np.ndarray) -> dict:
    models = {"mean": HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                                    min_samples_leaf=40, random_state=0).fit(X, y)}
    for name, q in QUANTILES.items():
        models[name] = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=300,
                                                     learning_rate=0.05, min_samples_leaf=40,
                                                     random_state=0).fit(X, y)
    return models


def training_frame(seasons: list[int], scoring: dict, through_week: int | None = None) -> pl.DataFrame:
    frames = []
    cur = data.current_season()
    for s in seasons:
        f = build_features(s, scoring)
        if s == cur and through_week is not None:
            f = f.filter(pl.col("week") < through_week)
        frames.append(f)
    return pl.concat(frames, how="diagonal_relaxed")


def backtest(scoring: dict, train: list[int], test: int) -> dict:
    """Train on `train` seasons, score every week of `test`. Compare with naive baselines."""
    tr = training_frame(train, scoring)
    te = build_features(test, scoring).filter(pl.col("games_prior") >= 2)
    models = _fit(*_xy(tr))
    X, y = _xy(te)
    pred = models["mean"].predict(X)
    p10, p90 = models["p10"].predict(X), models["p90"].predict(X)
    base_szn = te["fp_szn"].fill_null(0).to_numpy()
    base_xfp = te["xfp_szn"].fill_null(te["fp_szn"]).fill_null(0).to_numpy()
    mae = lambda a: float(np.mean(np.abs(a - y)))  # noqa: E731
    rank_corr = float(pl.DataFrame({"a": pred, "b": y}).select(pl.corr("a", "b", method="spearman")).item())
    return {
        "test_season": test, "rows": int(len(y)),
        "mae_model": round(mae(pred), 2),
        "mae_season_avg": round(mae(base_szn), 2),
        "mae_season_xfp": round(mae(base_xfp), 2),
        "spearman_model": round(rank_corr, 3),
        "p10_p90_coverage": round(float(np.mean((y >= p10) & (y <= p90))), 3),
    }


def train_and_save(scoring: dict, seasons: list[int], through_week: int) -> dict:
    tr = training_frame(seasons, scoring, through_week)
    models = _fit(*_xy(tr))
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    meta = {"seasons": seasons, "through_week": through_week, "rows": tr.height,
            "scoring": scoring, "features": FEATURES}
    with open(MODEL_PATH, "wb") as fh:
        pickle.dump({"models": models, "meta": meta}, fh)
    return meta


def load_model(scoring: dict, week: int) -> tuple[dict, dict]:
    """Load the saved model, retraining if it's stale for this week or scoring."""
    if MODEL_PATH.exists():
        with open(MODEL_PATH, "rb") as fh:
            saved = pickle.load(fh)
        m = saved["meta"]
        if m["through_week"] == week and m["scoring"] == scoring and m["features"] == FEATURES:
            return saved["models"], m
    cur = data.current_season()
    meta = train_and_save(scoring, list(range(cur - 4, cur + 1)), week)
    with open(MODEL_PATH, "rb") as fh:
        return pickle.load(fh)["models"], meta


def project(scoring: dict, season: int, week: int, player_ids: list[str] | None = None) -> pl.DataFrame:
    models, _ = load_model(scoring, week)
    rows = upcoming_rows(season, week, scoring)
    if player_ids:
        rows = rows.filter(pl.col("player_id").is_in(player_ids))
    rows = rows.filter(pl.col("games_prior") >= 2)
    if rows.height == 0:
        return rows
    X = rows.select(FEATURES).cast(pl.Float64).to_numpy()
    out = rows.with_columns(
        pl.Series("proj", models["mean"].predict(X)).round(1),
        pl.Series("p10", models["p10"].predict(X)).round(1),
        pl.Series("p50", models["p50"].predict(X)).round(1),
        pl.Series("p90", models["p90"].predict(X)).round(1),
    )
    return out.select("player", "position", "team", "opp", "home", "implied", "proj", "p10", "p50", "p90",
                      "fp_l3", "fp_szn", "xfp_szn", "games_prior").sort("proj", descending=True)
