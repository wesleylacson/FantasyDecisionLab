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

# Keep all double-click launchers executable. Repo-tracked launchers use executable mode,
# so this should not create local Git changes.
chmod +x "$DIR"/*.command 2>/dev/null || true

if [ -x "$DIR/.venv/bin/pip" ]; then
  "$DIR/.venv/bin/pip" install -r requirements.txt >/dev/null
fi

# Stop the main app if it was launched through its pidfile.
PIDFILE="$DIR/fantasy_decision_lab.pid"
if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE")"
  if kill "$PID" 2>/dev/null; then
    echo "Stopped the previously running main app so the update can take effect."
    sleep 1
  fi
  rm -f "$PIDFILE"
fi

# Projection Workbench live uses 8766; QA fixtures use 8767. Stop either stale server
# during updates so the next launcher always reflects the newest code.
if command -v lsof >/dev/null 2>&1; then
  for PORT in 8766 8767; do
    WORKBENCH_PID="$(lsof -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null | head -n 1)"
    if [ -n "$WORKBENCH_PID" ]; then
      WORKBENCH_CMD="$(ps -p "$WORKBENCH_PID" -o command= 2>/dev/null || true)"
      case "$WORKBENCH_CMD" in
        *projection_workbench*)
          if kill "$WORKBENCH_PID" 2>/dev/null; then
            echo "Stopped the previously running Projection Workbench on port $PORT so the update can take effect."
            sleep 1
          fi
          ;;
      esac
    fi
  done
fi

echo ""
echo "Update complete. Launch Fantasy Decision Lab, Projection Workbench, or Projection Workbench QA to start the newest version."
read -r -p "Press Return to close..."
