#!/usr/bin/env bash
# bootstrap.sh — set up FOB's isolated Python environment
# Safe to call repeatedly. Called by ControlPlane or on fresh clone.

set -euo pipefail

FOB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$FOB_DIR/.venv"

echo "▶ FOB bootstrap"
echo "  dir:  $FOB_DIR"
echo "  venv: $VENV"
echo

if [[ ! -d "$VENV" ]]; then
  echo "▶ Creating virtual environment..."
  python3 -m venv "$VENV"
fi

echo "▶ Installing requirements..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$FOB_DIR/requirements.txt"

echo
echo "✓ Bootstrap complete"
echo "  fob is ready — run: fob help"
