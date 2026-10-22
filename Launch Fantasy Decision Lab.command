#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
URL="http://127.0.0.1:8765"
PIDFILE="$DIR/fantasy_decision_lab.pid"

# Always prefer a clean restart so a stale process cannot keep an old
# API key/config/environment alive across launches.
if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    CMD="$(ps -p "$PID" -o command= 2>/dev/null || true)"
    case "$CMD" in
      *"$DIR/"*)
        kill "$PID" 2>/dev/null || true
        ;;
    esac
  fi
  rm -f "$PIDFILE"
fi

# If the PID file was stale/missing but this project still owns port 8765,
# stop that process too. Never kill an unrelated process using the port.
if command -v lsof >/dev/null 2>&1; then
  LISTENER_PID="$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  if [ -n "$LISTENER_PID" ]; then
    CMD="$(ps -p "$LISTENER_PID" -o command= 2>/dev/null || true)"
    case "$CMD" in
      *"$DIR/"*)
        kill "$LISTENER_PID" 2>/dev/null || true
        ;;
      *)
        echo "Port 8765 is already in use by another process:"
        echo "$CMD"
        echo "Fantasy Decision Lab will not stop an unrelated process."
        read -r -p "Press Return to close..."
        exit 1
        ;;
    esac
  fi
fi

# Give the previous server a moment to release the port.
for i in {1..20}; do
  if ! lsof -tiTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done

if [ ! -x "$DIR/.venv/bin/python" ] || [ ! -f "$HOME/.fantasy_decision_lab/config.json" ]; then
  echo "Fantasy Decision Lab needs first-time setup."
  open "$DIR/First-time Setup.command"
  exit 0
fi

APP_ENTRY="$DIR/app_v0318.py"
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v0317.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v0316.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v0315.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v0314.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v0313.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v0312.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v0310.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v039.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v038.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v037.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v036.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v035.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v034.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v033.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v032.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v03.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v021.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app_v02.py"; fi
if [ ! -f "$APP_ENTRY" ]; then APP_ENTRY="$DIR/app.py"; fi

nohup "$DIR/.venv/bin/python" "$APP_ENTRY" > "$DIR/fantasy_decision_lab.log" 2>&1 &
echo $! > "$PIDFILE"

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
