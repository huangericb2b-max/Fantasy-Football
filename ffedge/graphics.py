"""Matchup cards: one self-contained HTML page with an SVG card per player.

Each card shows:
  - header: matchup, line, projection with 80% range
  - weekly role chart (snap share + target or rush share)
  - points vs expected points by week
  - where the player gets the ball (target map or run-lane map)
  - where the opposing defense gives up EPA in those same zones vs league average
  - opposing coverage / blitz profile vs league average
  - offense vs defense rank comparison

No plotting library: SVG is written by hand so the page opens anywhere,
works offline, and follows light/dark mode.
"""
from __future__ import annotations

import html
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl

from . import data, matchup, project, usage
from .config import League

# Palette (validated reference palette, see .claude/skills dataviz notes)
BLUE_RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
             "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
DIV_COOL = ["#f0efec", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf"]   # softer than avg (good for offense)
DIV_WARM = ["#f0efec", "#fbd9d6", "#f6b3ae", "#ef8a85", "#e34948", "#b8302f"]   # tougher than avg

DEPTHS = [("Deep 20+", 20, 99), ("Mid 10-19", 10, 19), ("Short 0-9", 0, 9), ("Behind LOS", -99, -1)]
SIDES = ["left", "middle", "right"]
LANES = [("left", "end"), ("left", "tackle"), ("left", "guard"), ("middle", None),
         ("right", "guard"), ("right", "tackle"), ("right", "end")]
LANE_LABEL = ["L end", "L tackle", "L guard", "Middle", "R guard", "R tackle", "R end"]

CSS = """
.viz-root{color-scheme:light;--surface-0:#f4f3f0;--surface-1:#fcfcfb;--text-primary:#0b0b0b;
--text-secondary:#52514e;--text-muted:#7a7974;--grid:#e4e3df;--axis:#bdbcb7;--series-1:#2a78d6;
--series-2:#eb6834;--range:#cde2fb;font-family:Aptos,Calibri,Arial,sans-serif;background:var(--surface-0);
color:var(--text-primary);margin:0;padding:16px}
@media (prefers-color-scheme:dark){.viz-root{color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;
--text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#94938c;--grid:#2c2c2a;--axis:#4a4a46;
--series-1:#3987e5;--series-2:#d95926;--range:#184f95}}
h1{font-size:22px;margin:0 0 4px} .sub{color:var(--text-secondary);font-size:13px;margin-bottom:16px}
.card{background:var(--surface-1);border-radius:8px;padding:16px;margin:0 auto 20px;max-width:760px}
.card h2{font-size:20px;margin:0} .meta{color:var(--text-secondary);font-size:13px;margin:2px 0 12px}
.row{display:flex;flex-wrap:wrap;gap:12px} .col{flex:1 1 340px;min-width:300px}
.ct{font-size:13px;font-weight:600;margin:10px 0 2px} .cn{font-size:11px;color:var(--text-muted);margin:0 0 4px}
svg text{fill:var(--text-primary);font-family:inherit} svg .t2{fill:var(--text-secondary)} svg .t3{fill:var(--text-muted)}
.hero{display:flex;align-items:baseline;gap:10px;margin:4px 0}
.hero b{font-size:34px} .hero span{color:var(--text-secondary);font-size:13px}
details{font-size:12px;color:var(--text-secondary);margin-top:8px} table{border-collapse:collapse}
td,th{padding:2px 8px;text-align:right} th:first-child,td:first-child{text-align:left}
.foot{max-width:760px;margin:0 auto;color:var(--text-muted);font-size:11px}
"""


def _esc(x) -> str:
    return html.escape(str(x))


def _fmt(x, d=1, pct=False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x * 100:.{d}f}%" if pct else f"{x:.{d}f}"


def _seq_color(v: float, vmax: float) -> tuple[str, str]:
    if v <= 0 or vmax <= 0:
        return "var(--surface-0)", "var(--text-muted)"
    i = min(len(BLUE_RAMP) - 1, int(round((v / vmax) * (len(BLUE_RAMP) - 1))))
    return BLUE_RAMP[i], ("#ffffff" if i >= 6 else "#0b0b0b")


def _div_color(diff: float | None, n: int, scale: float, min_n: int) -> tuple[str, str]:
    if diff is None or n < min_n:
        return "var(--surface-0)", "var(--text-muted)"
    ramp = DIV_COOL if diff > 0 else DIV_WARM
    i = min(len(ramp) - 1, int(round(abs(diff) / scale * (len(ramp) - 1))))
    return ramp[i], ("#ffffff" if i >= 4 else "#0b0b0b")


# ---------- data prep ----------

def _pbp(season: int, before_week: int) -> pl.DataFrame:
    return data.load("pbp", season).filter(
        (pl.col("season_type") == "REG") & (pl.col("week") < before_week)
        & pl.col("play_type").is_in(["pass", "run"]) & (pl.col("two_point_attempt").fill_null(0) == 0)
    )


def _depth_expr() -> pl.Expr:
    ay = pl.col("air_yards")
    expr = pl.lit(None, dtype=pl.Utf8)
    for name, lo, hi in DEPTHS:
        expr = pl.when(ay.is_between(lo, hi)).then(pl.lit(name)).otherwise(expr)
    return expr


def _pass_cells(p: pl.DataFrame) -> pl.DataFrame:
    return p.filter(pl.col("pass_location").is_not_null() & pl.col("air_yards").is_not_null()).with_columns(
        _depth_expr().alias("depth"))


def _lane_expr() -> pl.Expr:
    expr = pl.lit(None, dtype=pl.Utf8)
    for (loc, gap), lab in zip(LANES, LANE_LABEL):
        cond = pl.col("run_location") == loc
        if gap:
            cond = cond & (pl.col("run_gap") == gap)
        expr = pl.when(cond).then(pl.lit(lab)).otherwise(expr)
    return expr


# ---------- SVG pieces ----------

def svg_line(weeks: list[int], series: list[tuple[str, list, str]], title: str, w=360, h=170) -> str:
    """Line chart on a 0-100% axis. series = [(name, values 0-1, css var)]."""
    l, r, t, b = 34, 64, 10, 24
    pw, ph = w - l - r, h - t - b
    allw = list(range(min(weeks), max(weeks) + 1)) if weeks else [1]
    x = lambda wk: l + (0 if len(allw) == 1 else (wk - allw[0]) / (allw[-1] - allw[0]) * pw)  # noqa: E731
    y = lambda v: t + ph - v * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" role="img" aria-label="{_esc(title)}">']
    for g in (0, .25, .5, .75, 1):
        out.append(f'<line x1="{l}" x2="{l + pw}" y1="{y(g):.1f}" y2="{y(g):.1f}" stroke="var(--grid)" stroke-width="1"/>')
        out.append(f'<text x="{l - 4}" y="{y(g) + 3:.1f}" font-size="10" text-anchor="end" class="t3">{int(g * 100)}%</text>')
    for wk in allw:
        out.append(f'<text x="{x(wk):.1f}" y="{h - 8}" font-size="10" text-anchor="middle" class="t3">{wk}</text>')
    for name, vals, color in series:
        pts = [(x(wk), y(v)) for wk, v in zip(weeks, vals) if v is not None and not math.isnan(v)]
        if not pts:
            continue
        out.append('<polyline fill="none" stroke="var(%s)" stroke-width="2" stroke-linejoin="round" points="%s"/>'
                   % (color, " ".join(f"{a:.1f},{c:.1f}" for a, c in pts)))
        for (a, c), wk, v in zip(pts, [wk for wk, v in zip(weeks, vals) if v is not None and not math.isnan(v)],
                                 [v for v in vals if v is not None and not math.isnan(v)]):
            out.append(f'<circle cx="{a:.1f}" cy="{c:.1f}" r="4" fill="var({color})" stroke="var(--surface-1)" stroke-width="2">'
                       f'<title>Week {wk}: {name} {v * 100:.0f}%</title></circle>')
        lx, ly = pts[-1]
        out.append(f'<text x="{lx + 8:.1f}" y="{ly + 4:.1f}" font-size="11" class="t2">{_esc(name)}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_points(weeks: list[int], fp: list, xfp: list, title: str, w=360, h=170) -> str:
    """Bars = league points, tick = expected points (xFP)."""
    l, r, t, b = 30, 8, 10, 24
    pw, ph = w - l - r, h - t - b
    vals = [v for v in fp + xfp if v is not None and not math.isnan(v)]
    vmax = max(10, math.ceil(max(vals or [10]) / 10) * 10)
    allw = list(range(min(weeks), max(weeks) + 1)) if weeks else [1]
    bw = min(22, pw / len(allw) * 0.6)
    x = lambda wk: l + (allw.index(wk) + 0.5) * pw / len(allw)  # noqa: E731
    y = lambda v: t + ph - v / vmax * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" role="img" aria-label="{_esc(title)}">']
    for g in range(0, vmax + 1, 10):
        out.append(f'<line x1="{l}" x2="{l + pw}" y1="{y(g):.1f}" y2="{y(g):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{l - 4}" y="{y(g) + 3:.1f}" font-size="10" text-anchor="end" class="t3">{g}</text>')
    for wk in allw:
        out.append(f'<text x="{x(wk):.1f}" y="{h - 8}" font-size="10" text-anchor="middle" class="t3">{wk}</text>')
    for wk, a, e in zip(weeks, fp, xfp):
        cx = x(wk)
        if a is not None and a > 0:
            top, bot = y(a), y(0)
            rad = min(4, (bot - top) / 2)
            out.append(f'<path d="M{cx - bw / 2:.1f},{bot:.1f} V{top + rad:.1f} Q{cx - bw / 2:.1f},{top:.1f} {cx - bw / 2 + rad:.1f},{top:.1f} '
                       f'H{cx + bw / 2 - rad:.1f} Q{cx + bw / 2:.1f},{top:.1f} {cx + bw / 2:.1f},{top + rad:.1f} V{bot:.1f} Z" '
                       f'fill="var(--series-1)"><title>Week {wk}: {a:.1f} pts, xFP {_fmt(e)}</title></path>')
        if e is not None and not math.isnan(e):
            out.append(f'<line x1="{cx - bw / 2 - 4:.1f}" x2="{cx + bw / 2 + 4:.1f}" y1="{y(e):.1f}" y2="{y(e):.1f}" '
                       f'stroke="var(--series-2)" stroke-width="3" stroke-linecap="round"><title>Week {wk}: xFP {e:.1f}</title></line>')
    out.append("</svg>")
    return "".join(out)


def svg_grid(rows: list[str], cols: list[str], cells: dict, title: str, w=340, cell_h=46) -> str:
    """cells[(row, col)] = (fill, text color, line1, line2, tooltip)."""
    l, t = 76, 18
    cw = (w - l - 4) / len(cols)
    h = t + cell_h * len(rows) + 4
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" role="img" aria-label="{_esc(title)}">']
    for j, c in enumerate(cols):
        out.append(f'<text x="{l + (j + .5) * cw:.1f}" y="12" font-size="10" text-anchor="middle" class="t2">{_esc(c)}</text>')
    for i, rlab in enumerate(rows):
        yy = t + i * cell_h
        out.append(f'<text x="{l - 6}" y="{yy + cell_h / 2 + 4:.1f}" font-size="10" text-anchor="end" class="t2">{_esc(rlab)}</text>')
        for j, c in enumerate(cols):
            fill, tc, l1, l2, tip = cells.get((rlab, c), ("var(--surface-0)", "var(--text-muted)", "", "", ""))
            xx = l + j * cw
            out.append(f'<g><rect x="{xx + 1:.1f}" y="{yy + 1:.1f}" width="{cw - 2:.1f}" height="{cell_h - 2}" rx="4" fill="{fill}"/>'
                       f'<text x="{xx + cw / 2:.1f}" y="{yy + cell_h / 2:.1f}" font-size="13" font-weight="600" text-anchor="middle" style="fill:{tc}">{_esc(l1)}</text>'
                       f'<text x="{xx + cw / 2:.1f}" y="{yy + cell_h / 2 + 14:.1f}" font-size="10" text-anchor="middle" style="fill:{tc}">{_esc(l2)}</text>'
                       f'<title>{_esc(tip)}</title></g>')
    out.append("</svg>")
    return "".join(out)


def svg_bars_vs_avg(items: list[tuple[str, float | None, float | None]], title: str, w=340) -> str:
    """Horizontal 0-100% bars with a league-average tick. items = [(label, value, league_avg)]."""
    l, r, rh = 110, 46, 26
    pw = w - l - r
    h = rh * len(items) + 18
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" role="img" aria-label="{_esc(title)}">']
    for i, (lab, v, avg) in enumerate(items):
        yy = i * rh + 4
        out.append(f'<text x="{l - 8}" y="{yy + 13}" font-size="11" text-anchor="end" class="t2">{_esc(lab)}</text>')
        out.append(f'<rect x="{l}" y="{yy + 4}" width="{pw}" height="12" rx="4" fill="var(--surface-0)"/>')
        if v is not None and not math.isnan(v):
            out.append(f'<rect x="{l}" y="{yy + 4}" width="{max(4, v * pw):.1f}" height="12" rx="4" fill="var(--series-1)">'
                       f'<title>{_esc(lab)}: {v * 100:.0f}% (league {_fmt(avg, 0, True)})</title></rect>')
            out.append(f'<text x="{l + pw + 6}" y="{yy + 14}" font-size="11">{v * 100:.0f}%</text>')
        else:
            out.append(f'<text x="{l + pw + 6}" y="{yy + 14}" font-size="11" class="t3">n/a</text>')
        if avg is not None and not math.isnan(avg):
            ax = l + avg * pw
            out.append(f'<line x1="{ax:.1f}" x2="{ax:.1f}" y1="{yy}" y2="{yy + 20}" stroke="var(--text-primary)" stroke-width="2"/>')
    out.append(f'<line x1="{l}" x2="{l + 14}" y1="{h - 6}" y2="{h - 6}" stroke="var(--text-primary)" stroke-width="2"/>'
               f'<text x="{l + 18}" y="{h - 2}" font-size="10" class="t3">league average</text>')
    out.append("</svg>")
    return "".join(out)


def svg_ranks(rows: list[tuple[str, int | None, int | None]], off_lab: str, def_lab: str, w=340) -> str:
    """Dumbbell on a 32 -> 1 scale (right = better). rows = [(metric, offense rank, defense rank)]."""
    l, r, rh = 130, 16, 28
    pw = w - l - r
    h = rh * len(rows) + 34
    x = lambda rk: l + (32 - rk) / 31 * pw  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" role="img" aria-label="Rank comparison">']
    for rk in (32, 16, 1):
        out.append(f'<text x="{x(rk):.1f}" y="10" font-size="10" text-anchor="middle" class="t3">{rk}</text>')
    for i, (lab, o, d) in enumerate(rows):
        yy = 22 + i * rh
        out.append(f'<text x="{l - 8}" y="{yy + 4}" font-size="11" text-anchor="end" class="t2">{_esc(lab)}</text>')
        out.append(f'<line x1="{l}" x2="{l + pw}" y1="{yy}" y2="{yy}" stroke="var(--grid)"/>')
        if o and d:
            out.append(f'<line x1="{x(o):.1f}" x2="{x(d):.1f}" y1="{yy}" y2="{yy}" stroke="var(--axis)" stroke-width="2"/>')
        if o:
            out.append(f'<circle cx="{x(o):.1f}" cy="{yy}" r="6" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"><title>{_esc(off_lab)}: rank {o}</title></circle>')
        if d:
            out.append(f'<circle cx="{x(d):.1f}" cy="{yy}" r="6" fill="var(--series-2)" stroke="var(--surface-1)" stroke-width="2"><title>{_esc(def_lab)}: rank {d}</title></circle>')
    ly = h - 8
    out.append(f'<circle cx="{l}" cy="{ly - 3}" r="5" fill="var(--series-1)"/><text x="{l + 9}" y="{ly + 1}" font-size="10" class="t2">{_esc(off_lab)}</text>'
               f'<circle cx="{l + 110}" cy="{ly - 3}" r="5" fill="var(--series-2)"/><text x="{l + 119}" y="{ly + 1}" font-size="10" class="t2">{_esc(def_lab)}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_range(proj: float, p10: float, p90: float, w=420) -> str:
    vmax = max(30, math.ceil(p90 / 5) * 5)
    l, r = 4, 4
    pw = w - l - r
    x = lambda v: l + max(0, v) / vmax * pw  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} 34" width="100%" style="max-width:{w}px" role="img" aria-label="Projection range">',
           f'<rect x="{l}" y="8" width="{pw}" height="10" rx="4" fill="var(--surface-0)"/>',
           f'<rect x="{x(p10):.1f}" y="8" width="{x(p90) - x(p10):.1f}" height="10" rx="4" fill="var(--range)">'
           f'<title>80% range {p10:.1f} to {p90:.1f}</title></rect>',
           f'<line x1="{x(proj):.1f}" x2="{x(proj):.1f}" y1="3" y2="23" stroke="var(--series-1)" stroke-width="3" stroke-linecap="round"/>',
           f'<text x="{x(p10):.1f}" y="32" font-size="10" text-anchor="middle" class="t3">{p10:.1f}</text>',
           f'<text x="{x(p90):.1f}" y="32" font-size="10" text-anchor="middle" class="t3">{p90:.1f}</text>',
           "</svg>"]
    return "".join(out)


# ---------- card assembly ----------

def _target_map(pp: pl.DataFrame, pid: str, id_col: str) -> tuple[str, int]:
    word = "comp" if id_col == "passer_player_id" else "catch"
    mine = pp.filter(pl.col(id_col) == pid)
    agg = mine.group_by(["depth", "pass_location"]).agg(
        pl.len().alias("n"), pl.col("complete_pass").mean().alias("comp"),
        pl.col("yards_gained").mean().alias("ypt"))
    total = int(agg["n"].sum()) if agg.height else 0
    vmax = float(agg["n"].max()) if agg.height else 0
    cells = {}
    for r in agg.iter_rows(named=True):
        fill, tc = _seq_color(r["n"], vmax)
        share = r["n"] / total if total else 0
        cells[(r["depth"], r["pass_location"])] = (
            fill, tc, f"{r['n']}", f"{share * 100:.0f}% | {r['comp'] * 100:.0f}% {word}",
            f"{r['depth']} {r['pass_location']}: {r['n']} targets ({share * 100:.0f}%), {r['comp'] * 100:.0f}% caught, {r['ypt']:.1f} yds/tgt")
    return svg_grid([d[0] for d in DEPTHS], [s.title() for s in SIDES],
                    {(k[0], k[1].title()): v for k, v in cells.items()}, "Target map"), total


def _def_pass_map(pp: pl.DataFrame, opp: str) -> str:
    lg = pp.group_by(["depth", "pass_location"]).agg(pl.col("epa").mean().alias("lg"))
    d = pp.filter(pl.col("defteam") == opp).group_by(["depth", "pass_location"]).agg(
        pl.len().alias("n"), pl.col("epa").mean().alias("epa"), pl.col("complete_pass").mean().alias("comp"))
    d = d.join(lg, on=["depth", "pass_location"])
    cells = {}
    for r in d.iter_rows(named=True):
        diff = r["epa"] - r["lg"]
        fill, tc = _div_color(diff, r["n"], 0.5, 8)
        cells[(r["depth"], r["pass_location"].title())] = (
            fill, tc, f"{diff:+.2f}", f"{r['n']} att",
            f"{opp} vs {r['depth']} {r['pass_location']}: {r['epa']:+.2f} EPA/att ({diff:+.2f} vs league), "
            f"{r['comp'] * 100:.0f}% completed, {r['n']} attempts" + ("" if r["n"] >= 8 else " (small sample, uncolored)"))
    return svg_grid([x[0] for x in DEPTHS], [s.title() for s in SIDES], cells, "Defense EPA by zone")


def _run_maps(p: pl.DataFrame, pid: str, opp: str) -> tuple[str, int]:
    runs = p.filter((pl.col("play_type") == "run") & (pl.col("qb_scramble").fill_null(0) == 0)).with_columns(
        _lane_expr().alias("lane")).filter(pl.col("lane").is_not_null())
    mine = runs.filter(pl.col("rusher_player_id") == pid).group_by("lane").agg(
        pl.len().alias("n"), pl.col("yards_gained").mean().alias("ypc"))
    total = int(mine["n"].sum()) if mine.height else 0
    vmax = float(mine["n"].max()) if mine.height else 0
    lg = runs.group_by("lane").agg(pl.col("epa").mean().alias("lg"))
    dd = runs.filter(pl.col("defteam") == opp).group_by("lane").agg(
        pl.len().alias("n"), pl.col("epa").mean().alias("epa"), pl.col("yards_gained").mean().alias("ypc")).join(lg, on="lane")
    cells = {}
    for r in mine.iter_rows(named=True):
        fill, tc = _seq_color(r["n"], vmax)
        cells[("His carries", r["lane"])] = (fill, tc, f"{r['n']}", f"{r['ypc']:.1f} ypc",
                                             f"{r['lane']}: {r['n']} carries ({r['n'] / total * 100:.0f}%), {r['ypc']:.1f} yds/carry")
    for r in dd.iter_rows(named=True):
        diff = r["epa"] - r["lg"]
        fill, tc = _div_color(diff, r["n"], 0.3, 10)
        cells[(f"{opp} D", r["lane"])] = (fill, tc, f"{diff:+.2f}", f"{r['ypc']:.1f} ypc",
                                          f"{opp} vs {r['lane']} runs: {r['epa']:+.2f} EPA/carry ({diff:+.2f} vs league), {r['ypc']:.1f} ypc, {r['n']} carries")
    short = ["LE", "LT", "LG", "Mid", "RG", "RT", "RE"]
    cells = {(k[0], short[LANE_LABEL.index(k[1])]): v for k, v in cells.items()}
    return svg_grid(["His carries", f"{opp} D"], short, cells, "Run lanes", w=560, cell_h=50), total


def _league_cov_avg(cov: pl.DataFrame, col: str) -> float | None:
    return float(cov[col].mean()) if cov.height and col in cov.columns else None


def build_html(league: League, names: list[str], season: int | None = None, week: int | None = None) -> str:
    ctx = data.week_context(season)
    season = ctx["season"]
    week = week or ctx["week"]
    now = datetime.now(ZoneInfo(league.timezone)).strftime("%a %b %d, %I:%M %p ET")

    weekly = usage.weekly_usage(season, league.scoring).filter(pl.col("week") < week)
    ids, missing = usage.find_players(weekly, names)
    summ = usage.summarize(weekly).filter(pl.col("player_id").is_in(ids))
    off, de = matchup.team_profiles(season, week)
    fpa = matchup.fantasy_points_allowed(season, week, league.scoring)
    cov_now, cov_prev = matchup.coverage_current(), matchup.coverage_baseline(season - 1)
    try:
        proj = project.project(league.scoring, season, week, ids)
    except Exception:  # noqa: BLE001
        proj = pl.DataFrame()
    sch = data.load("schedules", season).filter((pl.col("week") == week) & (pl.col("game_type") == "REG"))
    p = _pbp(season, week)
    pp = _pass_cells(p)

    cards = []
    kick = pl.concat([
        sch.select(pl.col("home_team").alias("team"), (pl.col("gameday") + " " + pl.col("gametime")).alias("ko")),
        sch.select(pl.col("away_team").alias("team"), (pl.col("gameday") + " " + pl.col("gametime")).alias("ko")),
    ])
    summ = summ.join(kick, on="team", how="left").sort(["ko", "team", "player"], nulls_last=True)
    for s in summ.iter_rows(named=True):
        team, pos, pid = s["team"], s["position"], s["player_id"]
        g = sch.filter((pl.col("home_team") == team) | (pl.col("away_team") == team))
        if g.height == 0:
            cards.append(f'<div class="card"><h2>{_esc(s["player"])}</h2><div class="meta">{pos}, {team}: no game in week {week} (bye)</div></div>')
            continue
        g = g.row(0, named=True)
        home = g["home_team"] == team
        opp = g["away_team"] if home else g["home_team"]
        spread = g["spread_line"]
        line = "line n/a" if spread is None else (
            f"{g['home_team'] if spread > 0 else g['away_team']} -{abs(spread):g}, O/U {g['total_line']:g}" if spread else "PK")
        o = off.filter(pl.col("team") == team).row(0, named=True) if off.filter(pl.col("team") == team).height else {}
        d = de.filter(pl.col("team") == opp).row(0, named=True) if de.filter(pl.col("team") == opp).height else {}
        f_ = fpa.filter((pl.col("team") == opp) & (pl.col("position") == pos))
        f_ = f_.row(0, named=True) if f_.height else {}
        pr = proj.filter(pl.col("player") == s["player"]) if proj.height else proj
        pr = pr.row(0, named=True) if pr.height else None

        wk = weekly.filter(pl.col("player_id") == pid).sort("week")
        weeks = wk["week"].to_list()
        share_name, share_col = ("Rush share", "rush_share") if pos in ("RB", "QB") else ("Target share", "target_share")
        role = svg_line(weeks, [("Snaps", wk["snap_share"].to_list(), "--series-1"),
                                (share_name, wk[share_col].to_list(), "--series-2")], "Weekly role")
        pts = svg_points(weeks, wk["fp"].to_list(), wk["xfp"].to_list(), "Points vs expected")

        if pos == "RB":
            map1, n1 = _run_maps(p, pid, opp)
            map_html = (f'<div class="ct">Where he runs, and what {opp} allows there</div>'
                        f'<div class="cn">Top: carries by lane (darker = more). Bottom: {opp} EPA/carry vs league; '
                        f'blue = softer than average, red = tougher. {n1} charted carries.</div>{map1}')
            tm, nt = _target_map(pp, pid, "receiver_player_id")
            if nt >= 10:
                map_html += (f'<div class="ct">Target map ({nt} targets)</div>'
                             f'<div class="cn">Air yards at the catch point vs field side.</div>{tm}')
        else:
            id_col = "passer_player_id" if pos == "QB" else "receiver_player_id"
            tm, nt = _target_map(pp, pid, id_col)
            noun = "attempts" if pos == "QB" else "targets"
            rate = "completion" if pos == "QB" else "catch"
            map_html = (f'<div class="row"><div class="col"><div class="ct">Where he gets the ball ({nt} {noun})</div>'
                        f'<div class="cn">Count, share, {rate} rate by depth and side. Darker = more.</div>{tm}</div>'
                        f'<div class="col"><div class="ct">Where {opp} gives it up</div>'
                        f'<div class="cn">{opp} EPA per pass vs league in each zone. Blue = softer, red = tougher, gray = under 8 attempts.</div>'
                        f'{_def_pass_map(pp, opp)}</div></div>')

        cn = cov_now.filter(pl.col("team") == opp).row(0, named=True) if cov_now.height and cov_now.filter(pl.col("team") == opp).height else None
        cp = cov_prev.filter(pl.col("team") == opp).row(0, named=True) if cov_prev.height and cov_prev.filter(pl.col("team") == opp).height else None
        src, cov = (f"{cn['source']}, {cn['as_of']}", cn) if cn else (f"{season - 1} season baseline (no {season} data entered)", cp)
        base = cov_now if cn else cov_prev
        cov_items = []
        if cov:
            for lab, col in [("Man", "man_rate"), ("Zone", "zone_rate"), ("MOFC (1-high)", "mofc_rate"), ("MOFO (2-high)", "mofo_rate")]:
                v = cov.get(col)
                cov_items.append((lab, None if v is None else float(v), _league_cov_avg(base, col)))
        cov_items.append((f"Blitz (FTN {season})", d.get("blitz_rate"), float(de["blitz_rate"].mean())))
        cov_items.append(("Pressure proxy", d.get("pressure_proxy"), float(de["pressure_proxy"].mean())))
        cov_svg = svg_bars_vs_avg(cov_items, "Coverage profile")

        ranks = svg_ranks([
            ("Pass EPA", o.get("pass_epa_rk"), d.get("pass_epa_rk")),
            ("Rush EPA", o.get("rush_epa_rk"), d.get("rush_epa_rk")),
            ("Pressure", o.get("pressure_allowed_rk"), d.get("pressure_rk")),
            ("Sack rate", o.get("sack_rate_rk"), d.get("sack_rate_rk")),
        ], f"{team} offense", f"{opp} defense")

        if pr:
            hero = (f'<div class="hero"><b>{pr["proj"]:.1f}</b><span>projected pts, 80% range {pr["p10"]:.1f} to {pr["p90"]:.1f} '
                    f'(model; no injury news)</span></div>{svg_range(pr["proj"], pr["p10"], pr["p90"])}')
        else:
            hero = '<div class="meta">No projection (fewer than 2 games).</div>'

        fpa_txt = (f"{opp} allows {_fmt(f_.get('fpa'))} pts/g to {pos}s ({_fmt(f_.get('adj_fpa'), 1)} vs their usual, rank {f_.get('adj_fpa_rk')} of 32 most generous)"
                   if f_ else "")
        table = (f"<details><summary>Numbers</summary><table><tr><th>Metric</th><th>Season</th><th>Last {s['g_recent']}</th></tr>"
                 f"<tr><td>Snap share</td><td>{_fmt(s['snap_szn'], 0, True)}</td><td>{_fmt(s['snap_recent'], 0, True)}</td></tr>"
                 f"<tr><td>Target share</td><td>{_fmt(s['tgt_sh_szn'], 0, True)}</td><td>{_fmt(s['tgt_sh_recent'], 0, True)}</td></tr>"
                 f"<tr><td>Rush share</td><td>{_fmt(s['rush_sh_szn'], 0, True)}</td><td>{_fmt(s['rush_sh_recent'], 0, True)}</td></tr>"
                 f"<tr><td>Red-zone share</td><td>{_fmt(s['rz_sh_szn'], 0, True)}</td><td>{_fmt(s['rz_sh_recent'], 0, True)}</td></tr>"
                 f"<tr><td>xFP/g</td><td>{_fmt(s['xfp_szn'])}</td><td>{_fmt(s['xfp_recent'])}</td></tr>"
                 f"<tr><td>Pts/g</td><td>{_fmt(s['fp_szn'])}</td><td>{_fmt(s['fp_recent'])}</td></tr></table></details>")

        cards.append(f"""
<div class="card">
<h2>{_esc(s['player'])}</h2>
<div class="meta">{pos}, {team} {'vs' if home else '@'} {opp} | {line} | {g['gameday']} {g['gametime']} ET</div>
{hero}
<div class="row">
<div class="col"><div class="ct">Weekly role</div><div class="cn">Snap share and {share_name.lower()} by week.</div>{role}</div>
<div class="col"><div class="ct">Points vs expected</div><div class="cn">Bars = league points. Orange tick = xFP (what the usage is usually worth).</div>{pts}</div>
</div>
{map_html}
<div class="row">
<div class="col"><div class="ct">{opp} defensive profile</div><div class="cn">Coverage from {_esc(src)}.</div>{cov_svg}</div>
<div class="col"><div class="ct">Who has the edge</div><div class="cn">Ranks out of 32, right = better. Blue = {team} offense, orange = {opp} defense.</div>{ranks}</div>
</div>
<div class="cn" style="margin-top:8px">{_esc(fpa_txt)}</div>
{table}
</div>""")

    miss = f"<div class='sub'>Not found: {_esc(', '.join(missing))}</div>" if missing else ""
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Matchup cards {season} wk {week}</title>
<style>{CSS}</style></head><body class="viz-root">
<div class="card" style="background:transparent;padding:0 16px"><h1>Matchup cards: {season} week {week}</h1>
<div class="sub">As of {now}. Charts use games through week {week - 1}. Hover any mark for details.</div>{miss}</div>
{''.join(cards)}
<div class="foot">Data: nflverse play-by-play, snap counts and player stats; ffverse expected points; FTN charting (blitz).
Pressure is a sacks + QB hits proxy. Projections are a model with no injury or news input.</div>
</body></html>"""
