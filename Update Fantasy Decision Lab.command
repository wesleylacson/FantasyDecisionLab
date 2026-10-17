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

echo ""
echo "Update complete. Close/relaunch the app to use the newest version."
read -r -p "Press Return to close..."
