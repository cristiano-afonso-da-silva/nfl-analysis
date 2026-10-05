# 100% NFL Hit Rates

This Python tool generates copy-ready NFL sheets such as:

```text
Falcons @ Saints 100% Hit Rates
Bijan Robinson 50+ Rushing Yards 4/4
Bijan Robinson 2+ Receptions 4/4
Drake London 25+ Receiving Yards 4/4
```

A line is at 100% when the player reached the threshold in **every game he has played this season** before the target week: 1 game going into Week 2, 3 games going into Week 4, 4 games going into Week 5, and so on. The `4/4` label is that game count. Games the player did not play are skipped. Each player and market shows the highest threshold he has hit every time, so a line moves down (for example from 70+ to 50+) rather than disappearing when he has a lower game. It does **not** mean the next-game probability is 100%.

## What the script supports

- Passing yards
- Passing touchdowns
- Interceptions thrown
- Rushing yards
- Receptions
- Receiving yards
- Longest reception, derived from play-by-play
- Anytime touchdown, defined as at least one rushing or receiving touchdown
- Full-week generation or selected matchups
- Automatic best-effort OUT/IR/PUP filtering
- Manual player exclusions
- Plain-text and CSV export
- Zero-stat games are preserved when a player took an offensive snap, so they cannot be silently skipped
- Games with a box-score line still count before snap counts are published

The data loader uses the `nflreadpy` Python package and nflverse public datasets. The public data is normally updated after completed games, but it can be delayed or corrected. Always verify final injuries, inactives and sportsbook availability before publishing.

## Setup

Open this folder in Cursor, then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Generate a single game

```bash
python nfl_hit_rates.py --season 2026 --week 4 --matchup ATL@NO
```

Use official team abbreviations and format the game as `AWAY@HOME`.

## Generate the entire week

```bash
python nfl_hit_rates.py --season 2026 --week 4
```

## Save the results

```bash
python nfl_hit_rates.py \
  --season 2026 \
  --week 4 \
  --matchup ATL@NO \
  --output output/falcons_saints.txt \
  --csv output/falcons_saints.csv
```

## Verify the underlying games

```bash
python nfl_hit_rates.py --season 2026 --week 4 --matchup ATL@NO --show-values
```

Example:

```text
Bijan Robinson 50+ Rushing Yards 4/4 [83/72/194/55]
```

The bracketed values are displayed from oldest to newest.

## Exclude an injured or inactive player manually

```bash
python nfl_hit_rates.py \
  --season 2026 \
  --week 4 \
  --matchup ATL@NO \
  --exclude-player "Travis Etienne"
```

Repeat `--exclude-player` for additional names. The manual flag is important because official inactive lists are generally confirmed close to kickoff and public injury data may be incomplete.

## Change the ladders

Edit `thresholds.json`. The script returns the highest listed threshold that the player reached in every game this season.

Example:

```json
"receiving_yards": [5, 10, 15, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100]
```

If the season values are `51`, `29` and `194`, the output is `25+ Receiving Yards 3/3`.

## Website

`site/` is the "100% NFL Hit Rates" website: pick a week, see every line where a player has hit in every game he played this season, grouped by game. For games that are already final, each line shows whether it hit again. The statistic at the top compares how many lines are still at 100% going into the selected week with how many there were in Week 2.

### Updating the data

Double-click **`Update Data.command`** in Finder. It downloads the newest nflverse data, rebuilds every week up to the current one, opens the website, and publishes the new data to the live site at https://cristiano-afonso-da-silva.github.io/nfl-analysis/. The first run also sets up the Python environment.

Or from a terminal:

```bash
source .venv/bin/activate
python export_site_data.py --season 2026
open site/index.html
```

When to update:

- **Before kickoff** (e.g. Sunday morning): picks up the latest OUT/IR list so injured players are removed.
- **After games finish:** nflverse usually posts stats a few hours after a game ends. Updating fills in hit/miss results and, once every game of a week is final, unlocks the next week.

`site/index.html` works when opened directly from disk. The live site is deployed by `.github/workflows/pages.yml`, which publishes the `site` folder to GitHub Pages on every push to `main` that changes it.

## Run tests

```bash
pytest -q
```

## Important production notes for Cursor

1. Keep `player_id` as the primary identity. Names can change or collide.
2. Do not describe a 100% hit rate as a predicted 100% probability.
3. Count every game the player played this season; never silently skip one.
4. Preserve the manual exclusion option even if injury automation is improved.
5. If adding sportsbook odds later, keep the historical hit-rate calculation separate from the odds provider.
6. Cache downloaded nflverse files so a weekly run does not repeatedly download full play-by-play datasets.

## Suggested Cursor prompt

```text
Open this project and review README.md, nfl_hit_rates.py, thresholds.json, and the tests.
First run pytest. Then install the live dependencies and run the ATL@NO example.
Fix any nflreadpy schema differences without changing the business rule:
100% means the player hit the threshold in every regular-season game he
played this season before the target matchup. Keep only the highest configured
threshold per player and market. Preserve copy-ready text output, CSV output,
injury exclusions, and longest-reception calculation from play-by-play.
```
