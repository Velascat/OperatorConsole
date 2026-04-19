# FOB — Forward Operating Base

A local operator console for Claude-driven development. One command opens a structured Zellij workspace — Claude in the main pane, git and shell alongside it, mission context loaded from disk.

## What You Get

- **`fob brief`** — interactive repo picker; opens (or resumes) a named Zellij session with per-project tabs
- **Structured workspace** — Claude in 60%, lazygit + logs + shell in the right column
- **`.fob/` mission files** — four local markdown files that give Claude explicit, persistent context across sessions
- **Auto-discovery** — every git repo under `~/Documents/GitHub/` appears in the picker automatically; no YAML required
- **Session persistence** — Zellij serialization survives terminal close and reboots

## What Happens When You Run `fob brief`

1. An interactive picker shows all repos under `~/Documents/GitHub/` (Tab to select multiple)
2. If you're already inside the `fob` Zellij session, your selection opens as new named tabs
3. Otherwise, a new session launches with a tab per selected repo
4. In each tab: Claude starts with `claude --continue` and reads `.fob/` mission files for context
5. lazygit, a log tail, and a shell live in the right column

```
┌─────────────────────────────────────────────┐
│  fob  │  videofoundry  │  controlplane  │   │  ← tab bar
├─────────────────────┬──────────────────┤
│                     │    lazygit       │
│   claude --cont.    ├──────────────────┤
│      (60%)          │  .fob/runtime.log│
│                     ├──────────────────┤
│                     │    shell         │
└─────────────────────┴──────────────────┘
│  NORMAL  │  fob  │  ...                │   │  ← status bar
```

## Why It Exists

`--continue` in Claude Code resumes the last conversation, but gives Claude no structured context about what was being worked on. `.fob/` provides that — a standing orders doc, an active mission, an objectives list, and a mission log. Claude reads these at startup and picks up exactly where things left off.

## Installation

```bash
cd ~/Documents/GitHub/FOB
./bootstrap.sh        # creates .venv, installs PyYAML
./fob install         # symlinks fob to ~/.local/bin
source ~/.bashrc
fob doctor            # verify dependencies
```

Dependencies: `zellij`, `claude` (Claude Code CLI), `lazygit`, `git`, `python3`, `fzf`

## First Run

```bash
fob brief             # pick a repo; .fob/ is auto-initialized if missing
```

That's it. No profile YAML needed to get started.

## `.fob/` Mission Files

Each repo gets a `.fob/` directory initialized by `fob init`. Four files:

| File | Purpose |
|------|---------|
| `standing-orders.md` | Claude's operating rules — branch policy, what not to do |
| `active-mission.md` | What's being worked on right now and the definition of done |
| `objectives.md` | Ordered task list — in-progress, up-next, done |
| `mission-log.md` | Running log of decisions, blockers, and session notes |

Claude reads all four at the start of each session. After progress, Claude updates `objectives.md` and `mission-log.md`. This is the continuity layer — not vague conversational memory, but explicit local state.

`fob resume` prints the current brief so you can inspect exactly what Claude will see.

## Commands

**Primary:**

| Command | Description |
|---------|-------------|
| `fob brief [repo]` | Pick repos and launch workspace (or add tabs to running session) |
| `fob brief --reset-layout` | Regenerate layout from defaults, discarding saved state |
| `fob attach` | Re-attach to the running `fob` session |
| `fob exit` | Kill the `fob` session and all panes |
| `fob init [repo]` | Initialize `.fob/` mission files in a repo |
| `fob resume` | Print current mission brief from `.fob/` |
| `fob status` | Show repo, branch, session, and `.fob/` state |
| `fob test` | Run project tests |
| `fob audit` | Run project audit |
| `fob doctor` | Check and install dependencies |

**Utility:**

| Command | Description |
|---------|-------------|
| `fob cheat` | Open keybinding reference (floating pane inside Zellij) |
| `fob rice` | Terminal ricing guide + tool installer |
| `fob install` | Symlink `fob` to `~/.local/bin` |

## Profiles (Optional)

Repos are auto-discovered — no YAML needed for basic use. Create `config/profiles/<name>.yaml` to configure custom Claude context files, peer repo awareness, or non-default helper commands.

See [docs/profiles.md](docs/profiles.md).

## Typical Session

```
$ fob brief
  ○ fob          ○ videofoundry    ○ controlplane
> [fob selected automatically — cwd match]

  Brief: fob
  → Creating session 'fob'
  → Layout: /tmp/fob-session.kdl

[Zellij opens — Claude pane starts, reads .fob/, continues from last session]
```

## Further Reading

- [docs/architecture.md](docs/architecture.md) — how the launcher, discovery, and layout generation work
- [docs/profiles.md](docs/profiles.md) — profile format and optional configuration
- [docs/guardrails.md](docs/guardrails.md) — safe branch practices and Claude operating model
