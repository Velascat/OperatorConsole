#!/usr/bin/env bash
# bootstrap.sh — set up OperatorConsole's isolated Python environment
# Safe to call repeatedly. Called by OperationsCenter or on fresh clone.

set -euo pipefail

CONSOLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$CONSOLE_DIR/.venv"

echo "▶ OperatorConsole bootstrap"
echo "  dir:  $CONSOLE_DIR"
echo "  venv: $VENV"
echo

if [[ ! -d "$VENV" ]]; then
  echo "▶ Creating virtual environment..."
  python3 -m venv "$VENV"
fi

echo "▶ Installing requirements..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$CONSOLE_DIR/requirements.txt"

echo
echo "✓ Bootstrap complete"
echo "  console is ready — run: console help"
