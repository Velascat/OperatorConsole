#!/usr/bin/env bash
# setup.sh — install OperatorConsole's repo wrapper as a shell command.

set -euo pipefail

CONSOLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "▶ OperatorConsole setup"
echo "  repo: $CONSOLE_DIR"

bash "$CONSOLE_DIR/bootstrap.sh"
"$CONSOLE_DIR/console" symlink
