#!/bin/bash
set +e

DATA_DIR="$HOME/.fantasy_decision_lab"
KEY_FILE="$DATA_DIR/openai_api_key"
mkdir -p "$DATA_DIR"

echo "Fantasy Decision Lab — OpenAI API Setup"
echo ""
echo "Create an API key at https://platform.openai.com/api-keys"
echo "Then paste it below. Input will stay hidden."
echo ""
read -r -s -p "OpenAI API key: " API_KEY
echo ""

API_KEY="$(printf '%s' "$API_KEY" | tr -d '\r\n')"
if [ -z "$API_KEY" ]; then
  echo "No key entered. Nothing changed."
  read -r -p "Press Return to close..."
  exit 1
fi

printf '%s' "$API_KEY" > "$KEY_FILE"
chmod 600 "$KEY_FILE" 2>/dev/null || true

echo "API key saved locally at ~/.fantasy_decision_lab/openai_api_key"
echo "It is not stored in the GitHub repo."
echo ""
echo "Setup complete. Launch Projection Workbench to use AI + live web research."
read -r -p "Press Return to close..."
