import polars as pl
import pytest

from ffedge.config import DEFAULT_SCORING, load_league
from ffedge.scoring import add_league_points


def _row(**kw):
    base = {c: 0 for c in [
        "receptions", "receiving_yards", "receiving_tds", "rushing_yards", "rushing_tds",
        "passing_yards", "passing_tds", "passing_interceptions", "rushing_fumbles_lost",
        "receiving_fumbles_lost", "sack_fumbles_lost", "passing_2pt_conversions",
        "rushing_2pt_conversions", "receiving_2pt_conversions"]}
    base.update(kw)
    return pl.DataFrame([base])


def test_full_ppr_receiver():
    df = add_league_points(_row(receptions=8, receiving_yards=104, receiving_tds=1), DEFAULT_SCORING)
    assert df["fp"][0] == pytest.approx(8 + 10.4 + 6)


def test_qb_line():
    df = add_league_points(_row(passing_yards=250, passing_tds=2, passing_interceptions=1,
                                rushing_yards=40), DEFAULT_SCORING)
    assert df["fp"][0] == pytest.approx(10 + 8 - 2 + 4)


def test_league_file_loads():
    lg = load_league()
    assert lg.scoring["reception"] == 1.0
    assert lg.scoring["rush_td"] == 6.0


@pytest.mark.network
def test_whiteboard_smoke():
    from ffedge import data, whiteboard
    ctx = data.week_context()
    text = whiteboard.build(load_league(), ["Ja'Marr Chase"], ctx["season"], ctx["week"])
    assert "Whiteboard data sheet" in text
