#!/usr/bin/env bash
# cheat.sh — full reference cheatsheet, designed to run in a floating pane

R='\033[0m'; B='\033[1m'; DIM='\033[2m'
GRN='\033[32m'; YLW='\033[33m'; CYN='\033[36m'; MAG='\033[35m'
COLS="${COLUMNS:-90}"

hr()    { printf "${DIM}%*s${R}\n" "$COLS" '' | tr ' ' '─'; }
sec()   { echo; hr; echo -e "  ${B}${CYN}$1${R}"; hr; }
K()     { printf "  ${YLW}%-26s${R} ${GRN}%s${R}\n" "$1" "$2"; }
CMD()   { printf "  ${CYN}%-26s${R} ${DIM}%s${R}\n" "$1" "$2"; }

clear
echo -e "${CYN}${B}"
cat << 'BANNER'
  ███████╗ ██████╗ ██████╗     CHEATSHEET
  ██╔════╝██╔═══██╗██╔══██╗
  █████╗  ██║   ██║██████╔╝
  ██╔══╝  ██║   ██║██╔══██╗
  ██║     ╚██████╔╝██████╔╝
  ╚═╝      ╚═════╝ ╚═════╝
BANNER
echo -e "${R}"

# ── FOB Commands ──────────────────────────────────────────────────────────────
sec "FOB COMMANDS"
CMD "fob brief [profile]"   "launch or attach to Zellij workspace"
CMD "fob attach [profile]"  "attach to existing session"
CMD "fob status"            "repo, branch, session, .fob/ state"
CMD "fob resume"            "print Claude mission brief"
CMD "fob init [repo]"       "initialize .fob/ mission files"
CMD "fob test"              "run project tests"
CMD "fob audit"             "run project audit"
CMD "fob doctor"            "check all dependencies"
CMD "fob rice"              "install / update dev tools"
CMD "fob cheat"             "this screen"
echo

# ── Zellij ────────────────────────────────────────────────────────────────────
sec "ZELLIJ  (prefix: Ctrl+a)"
echo -e "\n  ${B}Panes${R}"
K "Ctrl+a |"         "split vertical"
K "Ctrl+a -"         "split horizontal"
K "Ctrl+a h/j/k/l"   "navigate panes"
K "Ctrl+a z"         "zoom pane fullscreen"
K "Ctrl+a x"         "close pane"
K "Ctrl+a {"         "move pane left"
K "Ctrl+a }"         "move pane right"
echo -e "\n  ${B}Windows (tabs)${R}"
K "Ctrl+a n"         "new window"
K "Ctrl+a w"         "window list"
K "Ctrl+a 1-9"       "jump to window"
K "Ctrl+a ,"         "rename window"
echo -e "\n  ${B}Sessions${R}"
K "Ctrl+a d"         "detach session (keeps running)"
K "Ctrl+a s"         "session manager"
echo -e "\n  ${B}Scroll / Copy${R}"
K "Ctrl+a ["         "enter scroll mode"
K "j / k"            "scroll down / up"
K "Ctrl+a ]"         "exit scroll mode"
echo -e "\n  ${B}Misc${R}"
K "Ctrl+a ?"         "all keybindings"
K "Ctrl+a r"         "reload config"
echo

# ── Dev Tools ─────────────────────────────────────────────────────────────────
sec "DEV TOOLS"
echo -e "\n  ${B}fzf — fuzzy finder${R}"
CMD "Ctrl+r"              "fuzzy search shell history"
CMD "Ctrl+t"              "fuzzy search files"
CMD "Alt+c"               "fuzzy cd into directory"

echo -e "\n  ${B}lazygit — git TUI${R}"
CMD "space"               "stage / unstage file"
CMD "c"                   "commit"
CMD "p"                   "push"
CMD "P"                   "pull"
CMD "b"                   "branch menu"
CMD "?"                   "help / all keybindings"

echo -e "\n  ${B}eza — modern ls${R}"
CMD "eza --icons"         "ls with icons"
CMD "eza -la --git"       "long list with git status"
CMD "eza --tree -L 3"     "directory tree (3 levels)"

echo -e "\n  ${B}bat — syntax cat${R}"
CMD "bat <file>"          "view file with syntax highlight"
CMD "bat -l python <file>" "force language"

echo -e "\n  ${B}zoxide — smart cd${R}"
CMD "z <partial>"         "jump to most used matching dir"
CMD "zi"                  "interactive fuzzy jump (needs fzf)"

echo -e "\n  ${B}delta — git diffs${R}"
CMD "git diff"            "auto-uses delta if configured"
CMD "git log -p"          "syntax-highlighted patch log"

echo -e "\n  ${B}rg — ripgrep${R}"
CMD "rg <pattern>"        "search files recursively"
CMD "rg <pattern> -t py"  "search only Python files"
CMD "rg <pattern> -l"     "list matching files only"

echo -e "\n  ${B}fd — smart find${R}"
CMD "fd <name>"           "find files by name (respects .gitignore)"
CMD "fd -e py"            "find by extension"
CMD "fd -t d <name>"      "find directories only"
CMD "fd <name> src/"      "search within a directory"
echo

hr
echo -e "  ${DIM}press Ctrl+a z to zoom this pane  ·  Ctrl+a x to close${R}"
hr
echo

read -rsp "" 2>/dev/null || true
