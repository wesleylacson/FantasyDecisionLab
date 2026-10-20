#!/bin/bash
set +e
cd "$(dirname "$0")"

URL="http://127.0.0.1:8766"
KEY_FILE="$HOME/.fantasy_decision_lab/openai_api_key"
if [ -z "$OPENAI_API_KEY" ] && [ -f "$KEY_FILE" ]; then
  export OPENAI_API_KEY="$(tr -d '\r\n' < "$KEY_FILE")"
fi

if command -v lsof >/dev/null 2>&1 && lsof -iTCP:8766 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Projection Workbench is already running. Opening it in your browser..."
  open "$URL"
  exit 0
fi

PYTHON_BIN="python3"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

echo "Starting Projection Workbench..."
"$PYTHON_BIN" projection_workbench_app.py
STATUS=$?

if [ $STATUS -ne 0 ]; then
  echo ""
  echo "Projection Workbench exited with an error (status $STATUS)."
  echo "The error above is the useful part — copy/paste it back into ChatGPT."
  echo ""
  read -r -p "Press Return to close..."
fi

exit $STATUS
