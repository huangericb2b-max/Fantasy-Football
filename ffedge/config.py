"""League settings and roster loading."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SCORING = {
    "reception": 1.0, "rec_yard": 0.1, "rec_td": 6.0,
    "rush_yard": 0.1, "rush_td": 6.0,
    "pass_yard": 0.04, "pass_td": 4.0, "interception": -2.0,
    "fumble_lost": -2.0, "two_point": 2.0,
}


@dataclass
class League:
    name: str = "league"
    timezone: str = "America/New_York"
    scoring: dict = field(default_factory=lambda: dict(DEFAULT_SCORING))
    lineup: dict = field(default_factory=dict)


def load_league(path: Path | None = None) -> League:
    path = path or ROOT / "league.toml"
    if not path.exists():
        return League()
    raw = tomllib.loads(path.read_text())
    scoring = dict(DEFAULT_SCORING)
    scoring.update(raw.get("scoring", {}))
    lg = raw.get("league", {})
    return League(
        name=lg.get("name", "league"),
        timezone=lg.get("timezone", "America/New_York"),
        scoring=scoring,
        lineup=raw.get("lineup", {}),
    )


def load_roster(path: Path | None = None) -> dict:
    path = path or ROOT / "roster.toml"
    if not path.exists():
        return {"players": [], "watchlist": []}
    raw = tomllib.loads(path.read_text())
    return {"players": raw.get("players", []), "watchlist": raw.get("watchlist", [])}
