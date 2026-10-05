#!/usr/bin/env python3
"""Export 100% hit-rate results for the static website in ./site.

Examples:
    python export_site_data.py --season 2026            # every week up to the current one
    python export_site_data.py --season 2026 --weeks 4  # only refresh Week 4

Each target week is written to site/data/<season>-week-<week>.json and every
exported week is bundled into site/data/data.js, which site/index.html loads.
For games that are already final, every line is graded against the player's
actual result that week.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd

from nfl_hit_rates import (
    DEFAULT_THRESHOLDS_PATH,
    METRIC_LABELS,
    TEAM_NAMES,
    Hit,
    Matchup,
    as_pandas,
    build_engine_stats,
    generate_hits,
    load_excluded_injuries,
    load_live_data,
    load_thresholds,
    longest_receptions_from_pbp,
    matchups_from_schedule,
    merge_longest_receptions,
    nfl,
    normalize_team,
    prepare_weekly_stats,
    select_season_games,
)

SITE_DATA_DIR = Path(__file__).with_name("site") / "data"
FIRST_WEEK = 2  # Week 1 has no current-season games to look back on.


def clean(value: object) -> object:
    """Convert pandas/numpy scalars into JSON-safe Python values."""
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    if hasattr(value, "item"):
        return value.item()
    return value


def number(value: object) -> float | int | None:
    value = clean(value)
    if value is None:
        return None
    value = float(value)
    return int(value) if value.is_integer() else value


def regular_season(schedule: pd.DataFrame, season: int) -> pd.DataFrame:
    return schedule[
        pd.to_numeric(schedule["season"], errors="coerce").eq(season)
        & schedule["game_type"].astype(str).str.upper().eq("REG")
    ]


def current_week(schedule: pd.DataFrame, season: int) -> int:
    """The first regular-season week that still has an unfinished game."""
    games = regular_season(schedule, season)
    unfinished = games[games["home_score"].isna() | games["away_score"].isna()]
    if unfinished.empty:
        return int(pd.to_numeric(games["week"]).max())
    return int(pd.to_numeric(unfinished["week"]).min())


def load_team_meta() -> dict[str, dict]:
    teams = as_pandas(nfl.load_teams())
    teams["team_abbr"] = teams["team_abbr"].map(normalize_team)
    teams = teams.drop_duplicates(subset=["team_abbr"], keep="last").set_index("team_abbr")
    meta = {}
    for abbr, nickname in TEAM_NAMES.items():
        row = teams.loc[abbr] if abbr in teams.index else None
        meta[abbr] = {
            "abbr": abbr,
            "nickname": nickname,
            "name": clean(row["team_name"]) if row is not None else nickname,
            "color": clean(row["team_color"]) if row is not None else "#444444",
            "logo": clean(row["team_logo_espn"]) if row is not None else None,
        }
    return meta


def load_player_meta(players: pd.DataFrame) -> dict[str, dict]:
    columns = ["gsis_id", "position", "headshot", "jersey_number"]
    people = players[[c for c in columns if c in players.columns]].dropna(subset=["gsis_id"])
    people = people.drop_duplicates(subset=["gsis_id"], keep="last")
    return {
        str(row["gsis_id"]): {
            "position": clean(row.get("position")),
            "headshot": clean(row.get("headshot")),
            "jersey": number(row.get("jersey_number")),
        }
        for _, row in people.iterrows()
    }


def team_records(schedule: pd.DataFrame, season: int, before_week: int) -> dict[str, str]:
    games = regular_season(schedule, season)
    games = games[
        pd.to_numeric(games["week"], errors="coerce").lt(before_week)
        & games["home_score"].notna()
        & games["away_score"].notna()
    ]
    record = {team: [0, 0, 0] for team in TEAM_NAMES}
    for game in games.itertuples(index=False):
        away, home = normalize_team(game.away_team), normalize_team(game.home_team)
        if game.away_score == game.home_score:
            record[away][2] += 1
            record[home][2] += 1
            continue
        winner, loser = (away, home) if game.away_score > game.home_score else (home, away)
        record[winner][0] += 1
        record[loser][1] += 1
    return {team: f"{w}-{l}" + (f"-{t}" if t else "") for team, (w, l, t) in record.items()}


def schedule_row(schedule: pd.DataFrame, season: int, week: int, matchup: Matchup) -> dict:
    rows = schedule[
        pd.to_numeric(schedule["season"], errors="coerce").eq(season)
        & pd.to_numeric(schedule["week"], errors="coerce").eq(week)
        & schedule["away_team"].map(normalize_team).eq(matchup.away)
        & schedule["home_team"].map(normalize_team).eq(matchup.home)
    ]
    return rows.iloc[0].to_dict() if not rows.empty else {}


def lookup_week(frame: pd.DataFrame, player_id: str, season: int, week: int) -> pd.Series | None:
    rows = frame[
        frame["player_id"].eq(player_id) & frame["season"].eq(season) & frame["week"].eq(week)
    ]
    return rows.iloc[0] if not rows.empty else None


def week_value(
    player_id: str, metric: str, season: int, week: int,
    engine_stats: pd.DataFrame, box_scores: pd.DataFrame,
) -> float | None:
    """The player's stat for one week, or None if he has no game data that week."""
    row = lookup_week(engine_stats, player_id, season, week)
    if row is None:
        row = lookup_week(box_scores, player_id, season, week)
    if row is None or metric not in row:
        return None
    return float(row[metric])


def grade_hit(
    hit: Hit,
    season: int,
    week: int,
    game_final: bool,
    engine_stats: pd.DataFrame,
    box_scores: pd.DataFrame,
    teams_with_stats: set[str],
    teams_with_snaps: set[str],
) -> dict:
    """Compare a line against the player's actual result in the target week.

    A player missing from the box score is only "dnp" once that team's snap
    counts are published; before that he may have played and recorded zero.
    """
    if not game_final or hit.team not in teams_with_stats:
        return {"status": "pending", "value": None}
    value = week_value(hit.player_id, hit.metric, season, week, engine_stats, box_scores)
    if value is None:
        status = "dnp" if hit.team in teams_with_snaps else "pending"
        return {"status": status, "value": None}
    return {"status": "hit" if value >= hit.threshold else "miss", "value": number(value)}


def export_week(
    season: int,
    week: int,
    schedule: pd.DataFrame,
    engine_stats: pd.DataFrame,
    box_scores: pd.DataFrame,
    thresholds: dict[str, list[int]],
    team_meta: dict[str, dict],
    player_meta: dict[str, dict],
    injury_filter: bool,
) -> dict:
    matchups = matchups_from_schedule(schedule, season, week)
    if not matchups:
        raise RuntimeError(f"No matchups found for {season} Week {week}")

    excluded_ids = (
        load_excluded_injuries([season - 1, season], season, week) if injury_filter else set()
    )
    records = team_records(schedule, season, week)
    teams_with_stats = set(
        box_scores.loc[box_scores["season"].eq(season) & box_scores["week"].eq(week), "team"]
    )
    teams_with_snaps = set(
        engine_stats.loc[engine_stats["season"].eq(season) & engine_stats["week"].eq(week), "team"]
    )

    games = []
    for matchup in matchups:
        hits = generate_hits(
            stats=engine_stats,
            teams={matchup.away, matchup.home},
            target_season=season,
            target_week=week,
            thresholds=thresholds,
            excluded_player_ids=excluded_ids,
        )
        info = schedule_row(schedule, season, week, matchup)
        away_score, home_score = number(info.get("away_score")), number(info.get("home_score"))
        game_final = away_score is not None and home_score is not None

        props = []
        for hit in hits:
            history = select_season_games(
                engine_stats[engine_stats["player_id"].eq(hit.player_id)], season, week
            )
            meta = player_meta.get(hit.player_id, {})
            props.append(
                {
                    "player_id": hit.player_id,
                    "player": hit.player_name,
                    "team": hit.team,
                    "position": meta.get("position"),
                    "headshot": meta.get("headshot"),
                    "market": hit.metric,
                    "market_label": METRIC_LABELS[hit.metric],
                    "threshold": hit.threshold,
                    "values": [number(v) for v in reversed(hit.values)],
                    "games": [
                        {"season": int(row.season), "week": int(row.week)}
                        for row in history.iloc[::-1].itertuples(index=False)
                    ],
                    "result": grade_hit(
                        hit, season, week, game_final, engine_stats, box_scores,
                        teams_with_stats, teams_with_snaps,
                    ),
                }
            )

        games.append(
            {
                "id": clean(info.get("game_id")) or f"{season}_{week:02d}_{matchup.away}_{matchup.home}",
                "away": matchup.away,
                "home": matchup.home,
                "title": matchup.title,
                "gameday": clean(info.get("gameday")),
                "gametime": clean(info.get("gametime")),
                "away_score": away_score,
                "home_score": home_score,
                "final": game_final,
                "away_record": records.get(matchup.away),
                "home_record": records.get(matchup.home),
                "props": props,
            }
        )

    games.sort(key=lambda g: (g["gameday"] or "", g["gametime"] or "", g["id"]))
    return {
        "season": season,
        "week": week,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": team_meta,
        "games": games,
    }


def write_bundle(season: int, total_weeks: int, live_week: int) -> None:
    files = sorted(
        SITE_DATA_DIR.glob(f"{season}-week-*.json"),
        key=lambda p: int(p.stem.rsplit("-", 1)[1]),
    )
    bundle = {
        "season": season,
        "total_weeks": total_weeks,
        "current_week": live_week,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weeks": [json.loads(p.read_text(encoding="utf-8")) for p in files],
    }
    # Shipped as a script (not fetched JSON) so index.html also works from file://.
    (SITE_DATA_DIR / "data.js").write_text(
        "window.HIT_RATE_DATA = " + json.dumps(bundle, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export hit-rate data for the website")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument(
        "--weeks", type=int, nargs="+",
        help="Weeks to export (default: every week from Week 2 up to the current week)",
    )
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS_PATH)
    parser.add_argument("--no-injury-filter", action="store_true")
    args = parser.parse_args(argv)

    seasons = [args.season - 1, args.season]
    raw_stats, schedule, pbp, snap_counts, players = load_live_data(seasons)
    engine_stats = build_engine_stats(raw_stats, pbp, snap_counts, players)
    engine_stats["player_id"] = engine_stats["player_id"].astype(str)
    box_scores = prepare_weekly_stats(raw_stats)
    if not pbp.empty:
        box_scores = merge_longest_receptions(box_scores, longest_receptions_from_pbp(pbp))

    live_week = current_week(schedule, args.season)
    total_weeks = int(pd.to_numeric(regular_season(schedule, args.season)["week"]).max())
    weeks = args.weeks or list(range(FIRST_WEEK, live_week + 1))

    thresholds = load_thresholds(args.thresholds)
    team_meta = load_team_meta()
    player_meta = load_player_meta(players)

    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for week in weeks:
        payload = export_week(
            args.season, week, schedule, engine_stats, box_scores,
            thresholds, team_meta, player_meta, not args.no_injury_filter,
        )
        filename = f"{args.season}-week-{week}.json"
        (SITE_DATA_DIR / filename).write_text(json.dumps(payload, indent=1), encoding="utf-8")
        line_count = sum(len(g["props"]) for g in payload["games"])
        print(f"Week {week}: {len(payload['games'])} games, {line_count} lines at 100%")

    write_bundle(args.season, total_weeks, live_week)
    print(f"Website data updated (current week: {live_week}). Open site/index.html.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
