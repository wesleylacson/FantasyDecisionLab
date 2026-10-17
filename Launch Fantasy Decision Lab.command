#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
URL="http://127.0.0.1:8765"

if curl -fsS "$URL" >/dev/null 2>&1; then
  open "$URL"
  exit 0
fi

if [ ! -x "$DIR/.venv/bin/python" ] || [ ! -f "$HOME/.fantasy_decision_lab/config.json" ]; then
  echo "Fantasy Decision Lab needs first-time setup."
  open "$DIR/First-time Setup.command"
  exit 0
fi

APP_ENTRY="$DIR/app_v034.py"
if [ ! -f "$APP_ENTRY" ]; then
  APP_ENTRY="$DIR/app_v033.py"
fi
if [ ! -f "$APP_ENTRY" ]; then
  APP_ENTRY="$DIR/app_v032.py"
fi
if [ ! -f "$APP_ENTRY" ]; then
  APP_ENTRY="$DIR/app_v03.py"
fi
if [ ! -f "$APP_ENTRY" ]; then
  APP_ENTRY="$DIR/app_v021.py"
fi
if [ ! -f "$APP_ENTRY" ]; then
  APP_ENTRY="$DIR/app_v02.py"
fi
if [ ! -f "$APP_ENTRY" ]; then
  APP_ENTRY="$DIR/app.py"
fi

nohup "$DIR/.venv/bin/python" "$APP_ENTRY" > "$DIR/fantasy_decision_lab.log" 2>&1 &
echo $! > "$DIR/fantasy_decision_lab.pid"

for i in {1..30}; do
  if curl -fsS "$URL" >/dev/null 2>&1; then
    open "$URL"
    exit 0
  fi
  sleep 0.5
done

echo "Fantasy Decision Lab did not start successfully."
echo ""
tail -50 "$DIR/fantasy_decision_lab.log" 2>/dev/null || true
read -r -p "Press Return to close..."
exit 1
