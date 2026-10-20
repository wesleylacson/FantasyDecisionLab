#!/bin/bash
set -e
DIR="$HOME/.fantasy_decision_lab"
CONFIG="$DIR/projection_sheet_sync.json"
mkdir -p "$DIR"

echo "Fantasy Decision Lab — Projection Sheet Sync"
echo ""
echo "Before this step, deploy projection_sheet_bridge.gs as a Google Apps Script Web App."
echo "Use the same long random token in that script and here."
echo ""
read -r -p "Apps Script /exec URL: " URL
read -r -s -p "Shared sync token: " TOKEN
echo ""

if [ -z "$URL" ] || [ -z "$TOKEN" ]; then
  echo "URL and token are both required. Nothing was changed."
  read -r -p "Press Return to close..."
  exit 1
fi

python3 - "$CONFIG" "$URL" "$TOKEN" <<'PY'
import json, os, sys
path, url, token = sys.argv[1:]
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump({"url": url.strip(), "token": token.strip()}, f, indent=2)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
chmod 600 "$CONFIG"

echo ""
echo "Saved. The next live Projection Workbench launch will flush any queued projections"
echo "and future revisions will upsert the same player/week/league row instead of appending duplicates."
read -r -p "Press Return to close..."
