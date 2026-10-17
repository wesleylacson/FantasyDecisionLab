#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "Fantasy Decision Lab — First-time setup"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found on this Mac. Install Python 3, then run this setup again."
  read -r -p "Press Return to close..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating private Python environment..."
  python3 -m venv .venv
fi

PY="$DIR/.venv/bin/python"
PIP="$DIR/.venv/bin/pip"
"$PIP" install --upgrade pip >/dev/null
"$PIP" install -r requirements.txt

CONFIG_DIR="$HOME/.fantasy_decision_lab"
CONFIG_FILE="$CONFIG_DIR/config.json"
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

echo ""
read -r -s -p "Paste your FantasyPros API key (it will stay on this Mac): " FP_KEY
echo ""
if [ -z "$FP_KEY" ]; then
  echo "No key entered. Setup stopped."
  read -r -p "Press Return to close..."
  exit 1
fi

"$PY" - "$CONFIG_FILE" "$FP_KEY" <<'PY'
import json, os, sys
path, key = sys.argv[1], sys.argv[2]
with open(path, 'w', encoding='utf-8') as f:
    json.dump({'fantasypros_api_key': key}, f, indent=2)
os.chmod(path, 0o600)
PY

echo ""
echo "Setup complete. You can now double-click Launch Fantasy Decision Lab.command."
read -r -p "Press Return to close..."
