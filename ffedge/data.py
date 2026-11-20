"""Cached nflverse loaders.

Everything is cached as parquet under data/cache/. Current-season files refresh
after `max_age_hours`; past seasons never change, so they are cached forever.
Call `refresh()` (or `ffedge refresh`) to force a re-download.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import nflreadpy as nfl
import polars as pl

from .config import ROOT

CACHE = ROOT / "data" / "cache"
MAX_AGE_HOURS = 6

_LOADERS = {
    "pbp": nfl.load_pbp,
    "player_stats": nfl.load_player_stats,
    "snaps": nfl.load_snap_counts,
    "schedules": nfl.load_schedules,
    "injuries": nfl.load_injuries,
    "ff_opportunity": nfl.load_ff_opportunity,
    "ftn": nfl.load_ftn_charting,
    "participation": nfl.load_participation,
}


def current_season() -> int:
    now = datetime.now(ZoneInfo("America/New_York"))
    return now.year if now.month >= 9 else now.year - 1


def _cache_path(name: str, season: int) -> Path:
    return CACHE / f"{name}_{season}.parquet"


def _fresh(path: Path, season: int, max_age_hours: float) -> bool:
    if not path.exists():
        return False
    if season < current_season():
        return True
    return (time.time() - path.stat().st_mtime) < max_age_hours * 3600


def load(name: str, seasons: int | list[int], max_age_hours: float = MAX_AGE_HOURS) -> pl.DataFrame:
    """Load one nflverse dataset for one or more seasons, using the parquet cache."""
    if isinstance(seasons, int):
        seasons = [seasons]
    CACHE.mkdir(parents=True, exist_ok=True)
    frames = []
    for s in seasons:
        path = _cache_path(name, s)
        if _fresh(path, s, max_age_hours):
            frames.append(pl.read_parquet(path))
            continue
        try:
            df = _LOADERS[name]([s])
        except (ValueError, ConnectionError) as e:  # season not published for this dataset
            if path.exists():
                frames.append(pl.read_parquet(path))
                continue
            if name in {"participation"}:
                continue
            raise RuntimeError(f"Could not load {name} {s}: {e}") from e
        df.write_parquet(path)
        frames.append(df)
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="diagonal_relaxed")


def players() -> pl.DataFrame:
    path = CACHE / "players.parquet"
    CACHE.mkdir(parents=True, exist_ok=True)
    if path.exists() and (time.time() - path.stat().st_mtime) < 7 * 86400:
        return pl.read_parquet(path)
    df = nfl.load_players()
    df.write_parquet(path)
    return df


def refresh(season: int | None = None) -> list[str]:
    season = season or current_season()
    done = []
    for name in _LOADERS:
        try:
            load(name, season, max_age_hours=0)
            done.append(name)
        except RuntimeError:
            pass
    return done


def data_status(season: int | None = None) -> dict:
    """Latest week actually present in each dataset (check rows, not timestamps)."""
    season = season or current_season()
    out = {}
    for name in ["pbp", "player_stats", "snaps", "ff_opportunity", "ftn", "injuries"]:
        try:
            df = load(name, season)
            out[name] = int(df["week"].max()) if df.height else None
        except RuntimeError:
            out[name] = None
    return out


def week_context(season: int | None = None) -> dict:
    """Which week is next up, and which games in it are already final."""
    season = season or current_season()
    sch = load("schedules", season).filter(pl.col("game_type") == "REG")
    unplayed = sch.filter(pl.col("home_score").is_null())
    if unplayed.height == 0:
        week = int(sch["week"].max())
    else:
        week = int(unplayed["week"].min())
    wk = sch.filter(pl.col("week") == week)
    return {
        "season": season,
        "week": week,
        "final": wk.filter(pl.col("home_score").is_not_null())["game_id"].to_list(),
        "upcoming": wk.filter(pl.col("home_score").is_null())["game_id"].to_list(),
    }
