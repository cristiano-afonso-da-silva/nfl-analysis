#!/usr/bin/env python3
"""Generate NFL 100% hit-rate cheat sheets from nflverse data.

Examples:
    python nfl_hit_rates.py --season 2026 --week 5
    python nfl_hit_rates.py --season 2026 --week 5 --matchup ATL@NO
    python nfl_hit_rates.py --season 2026 --week 5 --matchup ATL@NO --output falcons_saints.txt

A line such as "4/4" means the player reached the listed threshold in every
game he played this season before the target week. It is not a prediction or
a guarantee for the upcoming game.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

try:
    import nflreadpy as nfl
except ImportError:  # Allows unit tests of the calculation engine without network packages.
    nfl = None


TEAM_NAMES = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
    "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
    "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jags", "KC": "Chiefs",
    "LA": "Rams", "LAC": "Chargers", "LV": "Raiders", "MIA": "Dolphins",
    "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks",
    "SF": "49ers", "TB": "Bucs", "TEN": "Titans", "WAS": "Commanders"
}

TEAM_ALIASES = {
    "GNB": "GB", "GBP": "GB", "KAN": "KC", "KCC": "KC", "LAR": "LA",
    "OAK": "LV", "SD": "LAC", "SDG": "LAC", "STL": "LA", "JAC": "JAX",
    "WSH": "WAS"
}

DEFAULT_THRESHOLDS_PATH = Path(__file__).with_name("thresholds.json")

METRIC_LABELS = {
    "passing_yards": "Passing Yards",
    "passing_tds": "Passing Touchdowns",
    "interceptions": "Interceptions",
    "rushing_yards": "Rushing Yards",
    "receptions": "Receptions",
    "receiving_yards": "Receiving Yards",
    "longest_reception": "Longest Reception",
    "anytime_touchdown": "Anytime Touchdown",
}

METRIC_ORDER = {
    "passing_yards": 0,
    "passing_tds": 1,
    "interceptions": 2,
    "rushing_yards": 3,
    "receptions": 4,
    "receiving_yards": 5,
    "longest_reception": 6,
    "anytime_touchdown": 7,
}


@dataclass(frozen=True)
class Matchup:
    away: str
    home: str

    @property
    def title(self) -> str:
        return f"{TEAM_NAMES.get(self.away, self.away)} @ {TEAM_NAMES.get(self.home, self.home)}"


@dataclass(frozen=True)
class Hit:
    player_id: str
    player_name: str
    team: str
    metric: str
    threshold: int
    values: tuple[float, ...]

    @property
    def line(self) -> str:
        games = len(self.values)
        if self.metric == "anytime_touchdown":
            return f"{self.player_name} Anytime Touchdown {games}/{games}"
        return f"{self.player_name} {self.threshold}+ {METRIC_LABELS[self.metric]} {games}/{games}"


def normalize_team(team: object) -> str:
    value = str(team).strip().upper()
    return TEAM_ALIASES.get(value, value)


def as_pandas(frame: object) -> pd.DataFrame:
    if isinstance(frame, pd.DataFrame):
        return frame.copy()
    if hasattr(frame, "to_pandas"):
        return frame.to_pandas()
    return pd.DataFrame(frame)


def first_existing(columns: Iterable[str], candidates: Sequence[str]) -> str | None:
    available = set(columns)
    return next((name for name in candidates if name in available), None)


def require_columns(df: pd.DataFrame, columns: Sequence[str], label: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def load_thresholds(path: Path) -> dict[str, list[int]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    expected = set(METRIC_LABELS)
    missing = expected.difference(raw)
    if missing:
        raise ValueError(f"Threshold file is missing: {', '.join(sorted(missing))}")
    return {metric: sorted({int(value) for value in values}) for metric, values in raw.items()}


def parse_matchup(raw: str) -> Matchup:
    text = raw.upper().replace(" ", "")
    if "@" not in text:
        raise argparse.ArgumentTypeError("Use AWAY@HOME, for example ATL@NO")
    away, home = (normalize_team(part) for part in text.split("@", maxsplit=1))
    if away not in TEAM_NAMES or home not in TEAM_NAMES:
        raise argparse.ArgumentTypeError(f"Unknown team abbreviation in {raw!r}")
    return Matchup(away=away, home=home)


def prepare_weekly_stats(stats: pd.DataFrame) -> pd.DataFrame:
    """Normalize nflverse weekly player statistics to the engine schema."""
    stats = stats.copy()
    player_name_col = first_existing(
        stats.columns,
        ["player_display_name", "player_name", "name"],
    )
    team_col = first_existing(stats.columns, ["recent_team", "team", "team_abbr"])
    season_type_col = first_existing(stats.columns, ["season_type", "game_type"])
    if player_name_col is None or team_col is None:
        raise ValueError("Could not find player-name or team columns in nflverse player stats")

    rename = {player_name_col: "player_name", team_col: "team"}
    # nflverse ships both player_name (short) and player_display_name; drop the
    # one being replaced so the renamed column is unique.
    clashing = [new for old, new in rename.items() if old != new and new in stats.columns]
    stats = stats.drop(columns=clashing).rename(columns=rename)
    require_columns(stats, ["player_id", "season", "week"], "Player stats")

    if season_type_col:
        stats = stats[stats[season_type_col].astype(str).str.upper().eq("REG")]

    stats["player_id"] = stats["player_id"].astype(str)
    stats["team"] = stats["team"].map(normalize_team)
    stats["season"] = pd.to_numeric(stats["season"], errors="coerce")
    stats["week"] = pd.to_numeric(stats["week"], errors="coerce")

    numeric_defaults = {
        "passing_yards": 0,
        "passing_tds": 0,
        "interceptions": 0,
        "rushing_yards": 0,
        "rushing_tds": 0,
        "receptions": 0,
        "receiving_yards": 0,
        "receiving_tds": 0,
    }
    for column, default in numeric_defaults.items():
        if column not in stats:
            stats[column] = default
        stats[column] = pd.to_numeric(stats[column], errors="coerce").fillna(default)

    stats["anytime_touchdown"] = stats["rushing_tds"] + stats["receiving_tds"]
    return stats


def longest_receptions_from_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    """Return one maximum completed-pass gain per receiver/season/week."""
    pbp = pbp.copy()
    id_col = first_existing(pbp.columns, ["receiver_player_id", "receiver_id"])
    name_col = first_existing(pbp.columns, ["receiver_player_name", "receiver_name"])
    team_col = first_existing(pbp.columns, ["posteam", "team"])
    if id_col is None:
        return pd.DataFrame(columns=["player_id", "season", "week", "longest_reception"])
    require_columns(pbp, ["season", "week", "yards_gained"], "Play-by-play")

    if "season_type" in pbp:
        pbp = pbp[pbp["season_type"].astype(str).str.upper().eq("REG")]
    if "complete_pass" in pbp:
        pbp = pbp[pd.to_numeric(pbp["complete_pass"], errors="coerce").fillna(0).eq(1)]
    elif "pass_attempt" in pbp:
        pbp = pbp[pd.to_numeric(pbp["pass_attempt"], errors="coerce").fillna(0).eq(1)]

    pbp = pbp[pbp[id_col].notna()].copy()
    pbp["yards_gained"] = pd.to_numeric(pbp["yards_gained"], errors="coerce").fillna(0).clip(lower=0)
    group_cols = [id_col, "season", "week"]
    aggregate = {"yards_gained": "max"}
    if name_col:
        aggregate[name_col] = "last"
    if team_col:
        aggregate[team_col] = "last"

    longest = pbp.groupby(group_cols, as_index=False).agg(aggregate)
    rename = {id_col: "player_id", "yards_gained": "longest_reception"}
    if name_col:
        rename[name_col] = "pbp_player_name"
    if team_col:
        rename[team_col] = "pbp_team"
    longest = longest.rename(columns=rename)
    longest["player_id"] = longest["player_id"].astype(str)
    return longest


def merge_longest_receptions(stats: pd.DataFrame, longest: pd.DataFrame) -> pd.DataFrame:
    if longest.empty:
        stats = stats.copy()
        stats["longest_reception"] = 0
        return stats
    merged = stats.merge(
        longest[["player_id", "season", "week", "longest_reception"]],
        on=["player_id", "season", "week"],
        how="left",
    )
    merged["longest_reception"] = pd.to_numeric(
        merged["longest_reception"], errors="coerce"
    ).fillna(0)
    return merged


def build_played_game_stats(
    stats: pd.DataFrame,
    snap_counts: pd.DataFrame,
    players: pd.DataFrame,
) -> pd.DataFrame:
    """Add zero-stat games for players who took an offensive snap.

    Weekly box-score data can omit a receiver who played but recorded no target
    or touch. Snap counts provide the player-game universe, so that game is
    correctly treated as a zero rather than silently skipped.
    """
    snaps = snap_counts.copy()
    people = players.copy()
    require_columns(
        snaps,
        ["season", "week", "pfr_player_id", "team", "position", "offense_snaps"],
        "Snap counts",
    )
    require_columns(people, ["gsis_id", "pfr_id"], "Players")
    display_col = first_existing(
        people.columns,
        ["display_name", "football_name", "full_name"],
    )
    if display_col is None:
        raise ValueError("Players data is missing a display-name column")

    if "game_type" in snaps:
        snaps = snaps[snaps["game_type"].astype(str).str.upper().eq("REG")]
    snaps["offense_snaps"] = pd.to_numeric(snaps["offense_snaps"], errors="coerce").fillna(0)
    skill_positions = {"QB", "RB", "FB", "WR", "TE"}
    snaps = snaps[
        snaps["offense_snaps"].gt(0)
        & snaps["position"].astype(str).str.upper().isin(skill_positions)
    ].copy()

    people = people[["gsis_id", "pfr_id", display_col]].dropna(subset=["gsis_id", "pfr_id"])
    people = people.drop_duplicates(subset=["pfr_id"], keep="last")
    played = snaps.merge(people, left_on="pfr_player_id", right_on="pfr_id", how="inner")
    played = played.rename(
        columns={"gsis_id": "player_id", display_col: "player_name"}
    )
    played["player_id"] = played["player_id"].astype(str)
    played["team"] = played["team"].map(normalize_team)
    played["season"] = pd.to_numeric(played["season"], errors="coerce")
    played["week"] = pd.to_numeric(played["week"], errors="coerce")
    base = played[["player_id", "player_name", "team", "season", "week"]].drop_duplicates(
        subset=["player_id", "season", "week"], keep="last"
    )

    metrics = [
        "passing_yards", "passing_tds", "interceptions", "rushing_yards",
        "rushing_tds", "receptions", "receiving_yards", "receiving_tds",
        "anytime_touchdown",
    ]
    available_metrics = [metric for metric in metrics if metric in stats.columns]
    weekly = stats[["player_id", "season", "week", *available_metrics]].drop_duplicates(
        subset=["player_id", "season", "week"], keep="last"
    )
    keys = ["player_id", "season", "week"]
    combined = base.merge(weekly, on=keys, how="left")

    # Snap counts are published later than box scores, and some players have no
    # pfr_id mapping. A skill player with a box-score line clearly played, so
    # keep those games rather than silently skipping them.
    box_only = stats.merge(base[keys], on=keys, how="left", indicator=True)
    box_only = box_only[box_only["_merge"].eq("left_only")]
    if "position" in box_only:
        box_only = box_only[box_only["position"].astype(str).str.upper().isin(skill_positions)]
    box_only = box_only[["player_id", "player_name", "team", "season", "week", *available_metrics]]
    combined = pd.concat([combined, box_only], ignore_index=True)

    for metric in metrics:
        if metric not in combined:
            combined[metric] = 0
        combined[metric] = pd.to_numeric(combined[metric], errors="coerce").fillna(0)
    return combined


def select_last_three(
    player_rows: pd.DataFrame,
    target_season: int,
    target_week: int,
) -> pd.DataFrame:
    before_target = player_rows[
        (player_rows["season"] < target_season)
        | ((player_rows["season"] == target_season) & (player_rows["week"] < target_week))
    ]
    before_target = before_target.sort_values(["season", "week"], ascending=[False, False])
    return before_target.head(3)


def select_season_games(
    player_rows: pd.DataFrame,
    target_season: int,
    target_week: int,
) -> pd.DataFrame:
    """Every game the player played this season before the target week, newest first."""
    this_season = player_rows[
        (player_rows["season"] == target_season) & (player_rows["week"] < target_week)
    ]
    return this_season.sort_values("week", ascending=False)


def highest_hit_threshold(values: Sequence[float], thresholds: Sequence[int]) -> int | None:
    if not values:
        return None
    floor = min(values)
    eligible = [threshold for threshold in thresholds if threshold <= floor]
    return max(eligible) if eligible else None


def generate_hits(
    stats: pd.DataFrame,
    teams: set[str],
    target_season: int,
    target_week: int,
    thresholds: dict[str, list[int]],
    excluded_player_ids: set[str] | None = None,
    excluded_player_names: set[str] | None = None,
    season_to_date: bool = True,
) -> list[Hit]:
    """Generate the highest 100% threshold for every supported player market.

    By default the window is every game the player played this season before
    the target week. With season_to_date=False it is his last three games,
    filled from the previous season when needed.
    """
    excluded_player_ids = excluded_player_ids or set()
    excluded_player_names_lower = {name.casefold() for name in (excluded_player_names or set())}
    stats = stats.copy()
    stats["team"] = stats["team"].map(normalize_team)

    eligible_ids = set(
        stats.loc[
            (stats["season"] == target_season)
            & (stats["week"] < target_week)
            & stats["team"].isin(teams),
            "player_id",
        ].astype(str)
    )

    hits: list[Hit] = []
    for player_id in sorted(eligible_ids):
        if player_id in excluded_player_ids:
            continue
        player_rows = stats[stats["player_id"].astype(str).eq(player_id)]
        if season_to_date:
            rows = select_season_games(player_rows, target_season, target_week)
            if rows.empty:
                continue
        else:
            rows = select_last_three(player_rows, target_season, target_week)
            if len(rows) != 3:
                continue

        newest = rows.iloc[0]
        player_name = str(newest["player_name"])
        team = normalize_team(newest["team"])
        if team not in teams or player_name.casefold() in excluded_player_names_lower:
            continue

        for metric in METRIC_LABELS:
            if metric not in rows.columns:
                continue
            values = tuple(float(value) for value in rows[metric].tolist())
            threshold = highest_hit_threshold(values, thresholds[metric])
            if threshold is None:
                continue
            hits.append(
                Hit(
                    player_id=player_id,
                    player_name=player_name,
                    team=team,
                    metric=metric,
                    threshold=threshold,
                    values=values,
                )
            )

    return sorted(
        hits,
        key=lambda hit: (hit.team, hit.player_name, METRIC_ORDER[hit.metric]),
    )


def load_excluded_injuries(
    seasons: Sequence[int], target_season: int, target_week: int
) -> set[str]:
    """Best-effort OUT/IR/PUP filtering; returns an empty set if unavailable."""
    if nfl is None or not hasattr(nfl, "load_injuries"):
        return set()
    try:
        injuries = as_pandas(nfl.load_injuries(list(seasons)))
    except Exception as exc:  # Data availability changes during the season.
        print(f"Warning: injury data unavailable ({exc}). Use --exclude-player if needed.", file=sys.stderr)
        return set()
    id_col = first_existing(injuries.columns, ["gsis_id", "player_id"])
    status_col = first_existing(injuries.columns, ["report_status", "status", "roster_status"])
    if id_col is None or status_col is None:
        return set()
    if "season" in injuries:
        season_values = pd.to_numeric(injuries["season"], errors="coerce")
        injuries = injuries[season_values.eq(target_season)]
    if "week" in injuries:
        week_values = pd.to_numeric(injuries["week"], errors="coerce")
        injuries = injuries[week_values.eq(target_week)]
    excluded_statuses = {"OUT", "RESERVE/INJURED", "INJURED RESERVE", "IR", "PUP"}
    return set(
        injuries.loc[
            injuries[status_col].astype(str).str.upper().isin(excluded_statuses), id_col
        ].dropna().astype(str)
    )


def matchups_from_schedule(schedule: pd.DataFrame, season: int, week: int) -> list[Matchup]:
    require_columns(schedule, ["season", "week", "away_team", "home_team"], "Schedule")
    rows = schedule[
        pd.to_numeric(schedule["season"], errors="coerce").eq(season)
        & pd.to_numeric(schedule["week"], errors="coerce").eq(week)
    ]
    if "game_type" in rows:
        rows = rows[rows["game_type"].astype(str).str.upper().eq("REG")]
    return [
        Matchup(normalize_team(row.away_team), normalize_team(row.home_team))
        for row in rows.itertuples(index=False)
    ]


def format_sheet(matchup: Matchup, hits: Sequence[Hit], include_values: bool = False) -> str:
    lines = [f"{matchup.title} 100% Hit Rates"]
    for team in (matchup.away, matchup.home):
        for hit in hits:
            if hit.team != team:
                continue
            line = hit.line
            if include_values:
                chronological = tuple(reversed(hit.values))
                rendered = "/".join(f"{value:g}" for value in chronological)
                line += f" [{rendered}]"
            lines.append(line)
    return "\n".join(lines)


def load_live_data(
    seasons: Sequence[int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if nfl is None:
        raise RuntimeError("nflreadpy is not installed. Run: pip install -r requirements.txt")
    try:
        stats = as_pandas(nfl.load_player_stats(list(seasons), summary_level="week"))
    except TypeError:
        # Compatibility with older nflreadpy releases whose default is weekly.
        stats = as_pandas(nfl.load_player_stats(list(seasons)))
    schedule = as_pandas(nfl.load_schedules(list(seasons)))
    snap_counts = as_pandas(nfl.load_snap_counts(list(seasons)))
    players = as_pandas(nfl.load_players())

    # PBP is only needed for longest reception. Loading both seasons makes the
    # rule genuinely "last three player games" even at the start of a season.
    pbp_frames = []
    for season in seasons:
        try:
            pbp_frames.append(as_pandas(nfl.load_pbp([season])))
        except Exception as exc:
            print(
                f"Warning: play-by-play unavailable for {season} ({exc}); "
                "longest-reception markets may be omitted.",
                file=sys.stderr,
            )
    pbp = pd.concat(pbp_frames, ignore_index=True) if pbp_frames else pd.DataFrame()
    return stats, schedule, pbp, snap_counts, players


def build_engine_stats(
    raw_stats: pd.DataFrame,
    pbp: pd.DataFrame,
    snap_counts: pd.DataFrame,
    players: pd.DataFrame,
) -> pd.DataFrame:
    stats = build_played_game_stats(
        prepare_weekly_stats(raw_stats), snap_counts=snap_counts, players=players
    )
    if not pbp.empty:
        return merge_longest_receptions(stats, longest_receptions_from_pbp(pbp))
    stats["longest_reception"] = 0
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate NFL season-to-date 100% hit-rate sheets")
    parser.add_argument("--season", type=int, required=True, help="Target NFL season, e.g. 2026")
    parser.add_argument("--week", type=int, required=True, help="Upcoming regular-season week")
    parser.add_argument(
        "--matchup",
        action="append",
        type=parse_matchup,
        help="Optional AWAY@HOME filter. Repeat for multiple matchups.",
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=DEFAULT_THRESHOLDS_PATH,
        help="JSON threshold configuration",
    )
    parser.add_argument("--output", type=Path, help="Write the copy-ready sheet to this file")
    parser.add_argument("--csv", type=Path, help="Also write every qualifying result to CSV")
    parser.add_argument("--show-values", action="store_true", help="Show the three source values")
    parser.add_argument(
        "--exclude-player",
        action="append",
        default=[],
        help="Exclude an injured/inactive player by exact display name; repeat as needed",
    )
    parser.add_argument(
        "--no-injury-filter",
        action="store_true",
        help="Do not attempt automatic OUT/IR/PUP filtering",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seasons = [args.season - 1, args.season]
    raw_stats, schedule, pbp, snap_counts, players = load_live_data(seasons)
    stats = build_engine_stats(raw_stats, pbp, snap_counts, players)

    scheduled_matchups = matchups_from_schedule(schedule, args.season, args.week)
    matchups = args.matchup or scheduled_matchups
    if args.matchup:
        scheduled_set = {(game.away, game.home) for game in scheduled_matchups}
        for matchup in args.matchup:
            if (matchup.away, matchup.home) not in scheduled_set:
                print(
                    f"Warning: {matchup.away}@{matchup.home} was not found in the Week {args.week} schedule.",
                    file=sys.stderr,
                )
    if not matchups:
        raise RuntimeError(f"No matchups found for {args.season} Week {args.week}")

    thresholds = load_thresholds(args.thresholds)
    excluded_ids = set()
    if not args.no_injury_filter:
        excluded_ids = load_excluded_injuries(seasons, args.season, args.week)

    all_hits: list[Hit] = []
    sheets: list[str] = []
    for matchup in matchups:
        hits = generate_hits(
            stats=stats,
            teams={matchup.away, matchup.home},
            target_season=args.season,
            target_week=args.week,
            thresholds=thresholds,
            excluded_player_ids=excluded_ids,
            excluded_player_names=set(args.exclude_player),
        )
        all_hits.extend(hits)
        sheets.append(format_sheet(matchup, hits, include_values=args.show_values))

    rendered = "\n\n".join(sheets) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "player_id": hit.player_id,
                "player_name": hit.player_name,
                "team": hit.team,
                "market": hit.metric,
                "threshold": hit.threshold,
                "games": len(hit.values),
                "values_oldest_first": "/".join(f"{v:g}" for v in reversed(hit.values)),
                "hit_rate": f"{len(hit.values)}/{len(hit.values)}",
            }
            for hit in all_hits
        ]
        pd.DataFrame(rows).to_csv(args.csv, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
