# Architecture

## Overview

```
fob (shell wrapper)
└── src/fob/cli.py              ← main dispatcher + repo discovery + profile picker
    ├── profile_loader.py       ← YAML profile loading + validation
    ├── launcher.py             ← Zellij session creation / tab management
    ├── layout.py               ← layout persistence (save/load/show/reset)
    ├── session_group.py        ← session group persistence (save/load last group for fob restore)
    ├── session.py              ← Zellij session state queries
    ├── guardrails.py           ← branch detection + warnings
    ├── bootstrap.py            ← Claude mission brief generation
    └── commands.py             ← all helper command implementations
```

## Entry Point

Running `fob` (no subcommand) is equivalent to `fob brief`. The shell wrapper (`fob`) runs first:

1. Check for `.venv/bin/python3` — if absent, run `bootstrap.sh` automatically (first run only)
2. Set `PYTHONPATH` to `src/`
3. Exec `python3 -m fob.cli` with any arguments

`fob brief` is preserved as an explicit alias; both paths are identical.

## Launcher Flow

`fob` / `fob brief`:

1. Scan `~/Documents/GitHub/` for git repos; overlay any YAML profiles from `config/profiles/`
2. If cwd is inside a known repo → always auto-select that repo, skip picker entirely
3. If that repo's tab is already open → `launch()` attaches without adding a duplicate tab
4. If cwd is outside all known repos (e.g. `~/Documents/GitHub/`) → single-select picker (fzf or numbered fallback)
5. `fob multi` → explicit multi-select picker (Tab to toggle); each selected repo opens as a named tab
6. For each selected repo: initialize `.fob/` if missing; if multiple repos selected, inject siblings as implicit peers in each briefing; write `.fob/.briefing`, ensure `CLAUDE.md`
7. Multi-repo layout: Claude pane starts at `~/Documents/GitHub/` instead of the individual repo root
8. Auto-save group to `~/.local/share/fob/last-session.json` (for `fob restore`)
9. Print structured brief block: `session attaching/creating (fob)`, `layout fresh/saved` (new sessions only), active mission snippet
10. Check branch via `guardrails.py` — warn if on main/master
11. If session `fob` exists → add each repo as a new named tab (skip if tab already open)
12. Otherwise → generate fresh KDL layout (or use saved layout if `--layout` flag passed), launch `zellij --session fob --new-session-with-layout <kdl>`

`fob restore`: loads `last-session.json`, resolves repo names against `_discover_repos()`, injects siblings as implicit peers (same logic as multi-select brief), regenerates briefings, then calls `launch()`. The saved timestamp is the original group creation time — `restore` does not overwrite it.

## Python Environment

FOB uses an isolated venv at `.venv/` inside the FOB repo root. `bootstrap.sh` creates it and installs `PyYAML` from `requirements.txt`. The `fob` wrapper triggers this automatically on first run — no manual setup step required.

## Zellij Session Model

FOB uses a **single named session**: `fob`. Each project opens as a **named tab** within that session.

- Tab bar and status bar are present in every tab via explicit chrome panes in each layout
- Running `fob` from inside the session adds tabs without re-attaching
- Dead (EXITED) sessions are auto-deleted before creating a new one
- `fob kill` terminates the session and all panes (with confirmation prompt); `tput reset` is run afterwards to clear any stale terminal state

Layout files:
- Session start: `/tmp/fob-session.kdl` — includes `default_tab_template` + named first tab
- New tabs: `/tmp/fob-tab-<name>.kdl` — panes + explicit chrome

Pane arrangement — **single repo**:
- **Left 30%**: Git (`lazygit`)
- **Center**: Claude (`claude --continue`) top + Shell (`bash`) bottom 15% — horizontal split
- **Right 15%**: Logs (`tail -f .fob/runtime.log`)

Pane arrangement — **multi repo** (single tab, tab name = joined repo names):
- **Left 28% stacked**: lazygit + logs for repos 0, 2, 4…
- **Center 44% horizontal split**: Claude (top ~85%) + Shell (bottom 15%) — both start at `~/Documents/GitHub/`
- **Right 28% stacked**: lazygit + logs for repos 1, 3, 5…

## Profiles

Profiles live in `config/profiles/<name>.yaml`. They are **optional** — any git repo under `~/Documents/GitHub/` is auto-discovered without one.

A profile adds:
- `claude.*` — bootstrap files, peer context, continue flag
- `panes.*` — per-pane command overrides
- `helpers.*` — commands for `fob test`, `fob audit`

Auto-discovered repos that have a matching YAML profile (by `repo_root`) use the profile config. Others get sensible defaults.

See [profiles.md](profiles.md) for format reference.

## Repo Discovery

`_discover_repos()` in `cli.py`:
1. Scans `~/Documents/GitHub/` for directories containing `.git/`
2. Builds a `name → {name, repo_root}` dict (lowercase key, original-case display name)
3. Overlays configured YAML profiles: any profile whose `repo_root` matches a discovered repo replaces the auto-generated entry

`_profile_for_cwd()` uses the same discovery to find which profile's `repo_root` contains the current directory — used by `fob status`, `fob resume`, `fob test`, and `fob audit`.

## Layout Persistence

Layout persistence is a separate, explicit feature — it is not coupled to general bootstrap or session startup.

`layout.py` provides:
- `save(repo_root, profile_name, kdl)` — writes `.fob/layout.kdl` + `.fob/layout.json` (metadata: backend, repo_root, profile_name, saved_at)
- `load(repo_root)` — returns `(meta, kdl_path)` only if repo_root matches; returns `None` on mismatch
- `load_any(repo_root)` — returns `(meta, kdl_path, is_current)` for show/reset regardless of mismatch
- `reset(repo_root)` — deletes both files

`fob brief` always generates a fresh layout. `fob brief --layout` is the explicit opt-in to restore a saved layout. `fob layout load` starts Zellij directly with the saved KDL (no briefing update).

## Two-Layer Continuity Model

FOB uses a two-layer model for Claude context:

**Layer 1 — Human-editable source files** (edit these directly):

| File | Role |
|------|------|
| `active-mission.md` | Current objective — singular, concise, replace when focus changes |
| `standing-orders.md` | Stable repo policy — branch rules, operating constraints, low-churn |
| `objectives.md` | Work inventory — in-progress, up-next, done |
| `mission-log.md` | Chronological log — decisions, stop points, what changed and why |

**Layer 2 — Compiled launch artifact** (generated, do not edit):

| File | Role |
|------|------|
| `.briefing` | Compiled startup context — all four files + runtime context, regenerated each launch |

`fob init` creates the source files from `templates/mission/` if missing. `fob` auto-inits on first launch.

`CLAUDE.md` in the repo root tells Claude to read `.fob/.briefing` as the primary startup context.

## Briefing Generation

`bootstrap.py` reads the four source files and compiles `.fob/.briefing` at launch time. The briefing includes:

- Active Mission, Standing Orders, Objectives, Mission Log (from source files)
- Runtime context: repo name, repo root, current branch, timestamp, profile name
- Peer sections if `claude.peers` is configured

The briefing is regenerated fresh on every `fob brief` run — it is always current.

`fob resume` prints the compiled briefing to stdout so the operator can inspect what Claude will see.

## State Boundaries

FOB state is distributed across four distinct layers:

| Layer | What persists | Location |
|-------|--------------|----------|
| Zellij | Session name, tabs, live pane processes | Zellij session manager |
| `.fob/` | Mission files, layout files, compiled briefing | `<repo>/.fob/` |
| CLI config | Profile YAML, repo discovery overrides | `config/profiles/*.yaml` |
| Global state | Last session group (for `fob restore`) | `~/.local/share/fob/last-session.json` |

These layers are independent. Resetting one does not affect the others. `fob reset` scopes resets explicitly:
- `--session` → kills Zellij session only
- `--layout` → deletes `.fob/layout.json` + `.fob/layout.kdl` only
- `--state` → deletes the four mission source files only
- bare `fob reset` → all three (with confirmation)

## Visibility Commands

`fob status` — shows session (running/stopped, attached/detached), layout (saved/none, metadata), branch, profile, and `.fob/` file presence. Active mission snippet is shown if the file exists.

`fob map` — structured full-state snapshot. Includes repo info, session state, layout metadata, and mission file presence. `--json` flag emits machine-readable JSON for tooling/piping.

## Dev Toolchain

`fob loadout` runs `tools/loadout.sh` — an interactive installer for the recommended dev toolchain (fzf, bat, eza, ripgrep, fd, zoxide, delta, lazygit, starship, fastfetch). Tools not available in Ubuntu's standard apt repos (eza, git-delta, fastfetch) use custom GitHub release installers.

`fob doctor` checks both core FOB dependencies and all loadout tools, with install status for each.
