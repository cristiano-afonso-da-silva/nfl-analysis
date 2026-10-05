#!/bin/bash
# Double-click in Finder to download the newest NFL data and refresh the website.
cd "$(dirname "$0")" || exit 1

year=$(date +%Y)
month=$(date +%-m)
# January and February games belong to the season that started the previous September.
if [ "$month" -lt 3 ]; then season=$((year - 1)); else season=$year; fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up Python environment..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi

echo "Downloading the newest $season NFL data..."
if .venv/bin/python export_site_data.py --season "$season"; then
  open site/index.html
  echo ""
  echo "Publishing to GitHub Pages..."
  git add site/data
  if git diff --cached --quiet; then
    echo "No data changes to publish."
  elif git commit -q -m "Update data $(date '+%Y-%m-%d %H:%M')" && git push -q; then
    echo "Published. The live site updates in about a minute:"
    echo "https://cristiano-afonso-da-silva.github.io/nfl-analysis/"
  else
    echo "Publishing failed. The local website is still updated."
  fi
  echo ""
  echo "Done. The website has been refreshed."
else
  echo ""
  echo "Update failed. See the message above."
fi
read -n 1 -s -r -p "Press any key to close this window."
