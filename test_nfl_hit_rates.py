import json
from pathlib import Path

import pandas as pd

from nfl_hit_rates import (
    Matchup,
    build_played_game_stats,
    format_sheet,
    generate_hits,
    load_thresholds,
    prepare_weekly_stats,
    select_season_games,
)


def fixture_stats() -> pd.DataFrame:
    rows = []
    games = [
        (2026, 1, 83, 8, 90, 24, 1),
        (2026, 2, 72, 3, 9, 4, 0),
        (2026, 3, 194, 2, 19, 17, 2),
    ]
    for season, week, rush_yards, receptions, rec_yards, longest, total_tds in games:
        rows.append(
            {
                "player_id": "bijan",
                "player_display_name": "Bijan Robinson",
                "recent_team": "ATL",
                "season": season,
                "week": week,
                "season_type": "REG",
                "passing_yards": 0,
                "passing_tds": 0,
                "interceptions": 0,
                "rushing_yards": rush_yards,
                "rushing_tds": total_tds,
                "receptions": receptions,
                "receiving_yards": rec_yards,
                "receiving_tds": 0,
                "longest_reception": longest,
            }
        )
    return pd.DataFrame(rows)


def test_highest_supported_thresholds(tmp_path: Path) -> None:
    threshold_path = tmp_path / "thresholds.json"
    threshold_path.write_text(
        json.dumps(
            {
                "passing_yards": [175, 200],
                "passing_tds": [1, 2],
                "interceptions": [1],
                "rushing_yards": [20, 40, 50, 60, 70, 80],
                "receptions": [1, 2, 3],
                "receiving_yards": [5, 10, 20],
                "longest_reception": [5, 10, 15],
                "anytime_touchdown": [1],
            }
        ),
        encoding="utf-8",
    )
    stats = prepare_weekly_stats(fixture_stats())
    thresholds = load_thresholds(threshold_path)
    hits = generate_hits(stats, {"ATL", "NO"}, 2026, 4, thresholds)
    by_metric = {hit.metric: hit.threshold for hit in hits}

    assert by_metric["rushing_yards"] == 70
    assert by_metric["receptions"] == 2
    assert by_metric["receiving_yards"] == 5
    assert "longest_reception" not in by_metric
    assert "anytime_touchdown" not in by_metric


def test_copy_ready_format(tmp_path: Path) -> None:
    threshold_path = tmp_path / "thresholds.json"
    threshold_path.write_text(
        json.dumps(
            {
                "passing_yards": [175], "passing_tds": [1], "interceptions": [1],
                "rushing_yards": [70], "receptions": [2], "receiving_yards": [5],
                "longest_reception": [5], "anytime_touchdown": [1]
            }
        ),
        encoding="utf-8",
    )
    stats = prepare_weekly_stats(fixture_stats())
    hits = generate_hits(stats, {"ATL", "NO"}, 2026, 4, load_thresholds(threshold_path))
    sheet = format_sheet(Matchup("ATL", "NO"), hits)

    assert sheet.startswith("Falcons @ Saints 100% Hit Rates")
    assert "Bijan Robinson 70+ Rushing Yards 3/3" in sheet
    assert "Bijan Robinson 2+ Receptions 3/3" in sheet


def test_played_zero_stat_game_is_not_skipped() -> None:
    raw = fixture_stats()
    raw = raw[raw["week"].ne(2)].copy()
    snaps = pd.DataFrame(
        [
            {
                "season": 2026, "week": week, "game_type": "REG",
                "pfr_player_id": "RobiBi01", "team": "ATL", "position": "RB",
                "offense_snaps": 40,
            }
            for week in (1, 2, 3)
        ]
    )
    players = pd.DataFrame(
        [{"gsis_id": "bijan", "pfr_id": "RobiBi01", "display_name": "Bijan Robinson"}]
    )
    completed = build_played_game_stats(prepare_weekly_stats(raw), snaps, players)
    week_two = completed.loc[completed["week"].eq(2)].iloc[0]

    assert week_two["rushing_yards"] == 0
    assert week_two["receptions"] == 0


def rushing_rows(games: list[tuple[int, int, int]]) -> pd.DataFrame:
    return prepare_weekly_stats(
        pd.DataFrame(
            [
                {
                    "player_id": "bijan", "player_display_name": "Bijan Robinson",
                    "recent_team": "ATL", "season": season, "week": week,
                    "season_type": "REG", "rushing_yards": yards,
                }
                for season, week, yards in games
            ]
        )
    )


def test_every_current_season_game_counts_after_week_four(tmp_path: Path) -> None:
    threshold_path = tmp_path / "thresholds.json"
    threshold_path.write_text(
        json.dumps(
            {
                "passing_yards": [175], "passing_tds": [1], "interceptions": [1],
                "rushing_yards": [30, 50, 70], "receptions": [1], "receiving_yards": [5],
                "longest_reception": [5], "anytime_touchdown": [1],
            }
        ),
        encoding="utf-8",
    )
    stats = rushing_rows([(2026, 1, 55), (2026, 2, 83), (2026, 3, 72), (2026, 4, 194)])
    hits = generate_hits(stats, {"ATL"}, 2026, 5, load_thresholds(threshold_path))
    rushing = next(hit for hit in hits if hit.metric == "rushing_yards")

    assert rushing.threshold == 50
    assert rushing.values == (194, 72, 83, 55)
    assert rushing.line == "Bijan Robinson 50+ Rushing Yards 4/4"


def test_only_current_season_games_count() -> None:
    stats = rushing_rows([(2025, 16, 40), (2025, 17, 61), (2026, 1, 83), (2026, 2, 72)])
    games = select_season_games(stats, 2026, 3)

    assert list(zip(games["season"], games["week"])) == [(2026, 2), (2026, 1)]


def test_week_two_uses_the_single_week_one_game(tmp_path: Path) -> None:
    threshold_path = tmp_path / "thresholds.json"
    threshold_path.write_text(
        json.dumps(
            {
                "passing_yards": [175], "passing_tds": [1], "interceptions": [1],
                "rushing_yards": [30, 50, 70], "receptions": [1], "receiving_yards": [5],
                "longest_reception": [5], "anytime_touchdown": [1],
            }
        ),
        encoding="utf-8",
    )
    stats = rushing_rows([(2025, 17, 20), (2026, 1, 83)])
    hits = generate_hits(stats, {"ATL"}, 2026, 2, load_thresholds(threshold_path))
    rushing = next(hit for hit in hits if hit.metric == "rushing_yards")

    assert rushing.threshold == 70
    assert rushing.values == (83,)
