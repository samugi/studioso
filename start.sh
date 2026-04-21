#!/bin/bash
# start.sh — macOS/Linux launcher for Study Agent
# Double-click this file or run: bash start.sh

# Move to the script's own directory
cd "$(dirname "$0")"

echo ""
echo "  Study Agent — Starting up..."
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "  ✗ Python 3 not found."
  echo "    Install it from: https://www.python.org/downloads/"
  echo ""
  read -p "Press Enter to close..."
  exit 1
fi

# Run the agent
.venv/bin/python main.py "$@"

# Keep window open if there was an error
if [ $? -ne 0 ]; then
  echo ""
  read -p "Press Enter to close..."
fi
