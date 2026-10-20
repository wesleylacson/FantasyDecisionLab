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

# Keep all double-click launchers executable. The repo now tracks the projection
# launcher with the executable bit so this should not create a local Git change.
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

# The Projection Workbench historically did not write a pidfile. If an older
# workbench is still listening on 8766, the launcher would otherwise reopen the
# stale process and make a successful update look unchanged. Only kill the
# listener when its command line identifies it as our projection workbench.
if command -v lsof >/dev/null 2>&1; then
  WORKBENCH_PID="$(lsof -iTCP:8766 -sTCP:LISTEN -t 2>/dev/null | head -n 1)"
  if [ -n "$WORKBENCH_PID" ]; then
    WORKBENCH_CMD="$(ps -p "$WORKBENCH_PID" -o command= 2>/dev/null || true)"
    case "$WORKBENCH_CMD" in
      *projection_workbench*)
        if kill "$WORKBENCH_PID" 2>/dev/null; then
          echo "Stopped the previously running Projection Workbench so the update can take effect."
          sleep 1
        fi
        ;;
    esac
  fi
fi

echo ""
echo "Update complete. Launch Fantasy Decision Lab or Projection Workbench to start the newest version."
read -r -p "Press Return to close..."
