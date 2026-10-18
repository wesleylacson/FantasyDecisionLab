#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "Fantasy Decision Lab — Update"
echo ""

if [ ! -d ".git" ]; then
  echo "This copy is not connected to GitHub yet."
  echo "Once the GitHub repo is connected, future updates will be one double-click."
  read -r -p "Press Return to close..."
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Git is not installed on this Mac."
  read -r -p "Press Return to close..."
  exit 1
fi

echo "Checking GitHub for updates..."
git pull --ff-only

if [ -x "$DIR/.venv/bin/pip" ]; then
  "$DIR/.venv/bin/pip" install -r requirements.txt >/dev/null
fi

# If an older app process is still running, stop it now so the next Launch
# actually starts the newly-updated entrypoint instead of reopening the old server.
PIDFILE="$DIR/fantasy_decision_lab.pid"
if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE")"
  if kill "$PID" 2>/dev/null; then
    echo "Stopped the previously running app so the update can take effect."
    sleep 1
  fi
  rm -f "$PIDFILE"
fi

echo ""
echo "Update complete. Launch Fantasy Decision Lab to start the newest version."
read -r -p "Press Return to close..."
