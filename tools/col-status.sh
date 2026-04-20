#!/usr/bin/env bash
# col-status.sh — live git status for one or more repos in a column pane
# Usage: col-status.sh <repo1> [repo2] ...

DIM='\033[2m'; B='\033[1m'; CYN='\033[36m'; GRN='\033[32m'
YLW='\033[33m'; RED='\033[31m'; R='\033[0m'

while true; do
    clear
    for repo in "$@"; do
        name=$(basename "$repo")
        branch=$(git -C "$repo" branch --show-current 2>/dev/null || echo "?")
        dirty=$(git -C "$repo" status --short 2>/dev/null)

        if [ -n "$dirty" ]; then
            printf "${B}${YLW}%-18s${R} ${DIM}%s${R}\n" "$name" "$branch"
        else
            printf "${B}${CYN}%-18s${R} ${DIM}%s${R}\n" "$name" "$branch"
        fi

        if [ -n "$dirty" ]; then
            echo "$dirty" | head -8 | while IFS= read -r line; do
                printf "  ${DIM}%s${R}\n" "$line"
            done
        else
            printf "  ${GRN}${DIM}clean${R}\n"
        fi
        echo
    done
    sleep 3
done
