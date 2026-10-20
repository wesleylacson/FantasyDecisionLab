#!/bin/bash
set +e
cd "$(dirname "$0")"

URL="http://127.0.0.1:8767"
export FANTASY_PROJECTION_MODE="qa"
export FANTASY_PROJECTION_PORT="8767"

if command -v lsof >/dev/null 2>&1 && lsof -iTCP:8767 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Projection Workbench QA is already running. Opening it in your browser..."
  open "$URL"
  exit 0
fi

PYTHON_BIN="python3"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

echo "Starting Projection Workbench QA..."
echo "QA mode uses fixtures only and will not make paid OpenAI API or web-search calls."
"$PYTHON_BIN" projection_workbench_nav.py
STATUS=$?

if [ $STATUS -ne 0 ]; then
  echo ""
  echo "Projection Workbench QA exited with an error (status $STATUS)."
  echo "The error above is the useful part — copy/paste it back into ChatGPT."
  echo ""
  read -r -p "Press Return to close..."
fi

exit $STATUS
