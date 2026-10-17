#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$DIR/fantasy_decision_lab.pid"
if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE")"
  if kill "$PID" 2>/dev/null; then
    echo "Fantasy Decision Lab stopped."
  else
    echo "The saved process was not running."
  fi
  rm -f "$PIDFILE"
else
  echo "No saved Fantasy Decision Lab process found."
fi
sleep 1
