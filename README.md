# FOB — Forward Operating Base

A persistent, repo-scoped operator workspace for Claude-driven development. Run `fob` from any repo — it attaches to your existing session or creates a new one, and Claude picks up exactly where you left off.

## What FOB Is

FOB maintains a persistent workspace that you can leave and return to without losing context.

- **Session persistence** — a single named Zellij session (`fob`) stays alive across terminal closes and reconnects; `fob brief` attaches to it or creates it
- **Context persistence** — `.fob/` mission files give Claude structured, explicit context that survives across sessions
- **Layout persistence** — save and restore workspace layouts on demand via `fob layout save/load`
- **Auto-discovery** — every git repo under `~/Documents/GitHub/` appears in the picker automatically; no YAML required

FOB is not a neutral bootstrap script or a multiplexer-agnostic tool. Zellij is a core dependency, and persistence is the point.

## Workspace Layout

**Single repo:**
```
┌────────────────────────────────────────────────────────┐
│  FOB  │  VideoFoundry  │  ...                         │  ← tab bar
├──────────┬──────────────────────────────┬──────────────┤
│          │                              │              │
│ lazygit  │      claude --continue       │     logs     │
│  (28%)   │           (44%)              │    (28%)     │
│          ├──────────────────────────────┤              │
│          │  shell  (15%)                │              │
└──────────┴──────────────────────────────┴──────────────┘
│  NORMAL  │  fob  │  ...                               │  ← status bar
```

Left 28%: `lazygit`. Center 44%: Claude + shell (15% bottom). Right 28%: logs. Same column widths as multi-repo.

**Multi repo (`fob multi`) — single tab:**
```
┌──────────────────────────────────────────────────────┐
│  FOB+VideoFoundry  │  ...                           │  ← tab bar
├──────────┬───────────────────────��──┬───────────────┤
│ lazygit  │                          │ lazygit       │
│ repo-A   │    claude --continue     │ repo-B        │
│ logs-A ▸ │       (GitHub/)          │ logs-B ▸      │
│          ├──────────────────────────┤               │
│          │  shell  (15%)            │               │
└──────────┴──────────────────────────┴───────────────┘
```

28% left + 28% right: per-repo lazygit+logs stacked (repos split evenly left/right). Center 44%: Claude + shell. Claude starts at `~/Documents/GitHub/`.

## What Happens When You Run `fob`

1. Python environment bootstraps itself if needed (first run only)
2. If inside a known repo → always auto-selects that repo, no picker
3. If that repo's tab is already open → attaches to the running session (no duplicate tab)
4. If outside all known repos (e.g. at `~/Documents/GitHub/`) → single-select picker
5. Session `fob` exists → adds repo as a new named tab
6. Session `fob` doesn't exist → generates layout, launches Zellij session
7. Claude starts with `claude --continue`; reads `.fob/.briefing` for structured context

Use `fob multi` to explicitly open multiple repos at once.

## Why It Exists

`claude --continue` resumes the last conversation but gives Claude no structured context. `.fob/` provides that — standing orders, active mission, objectives, and a mission log. Claude reads these at startup and picks up exactly where things left off.

## Installation

```bash
cd ~/Documents/GitHub/FOB
./fob install         # symlinks fob to ~/.local/bin (bootstraps Python env automatically)
source ~/.bashrc
fob doctor            # verify dependencies
```

Dependencies: `zellij`, `claude` (Claude Code CLI), `lazygit`, `git`, `python3`, `fzf`

## First Run

```bash
cd ~/Documents/GitHub/YourRepo
fob
```

`.fob/` is auto-initialized in the repo on first launch.

## State Boundaries

FOB state lives in three distinct layers:

| Layer | What persists | Location |
|-------|--------------|----------|
| Zellij | Session, tabs, pane arrangement | Zellij session manager |
| `.fob/` | Mission files, layout, compiled briefing | `<repo>/.fob/` |
| CLI | Orchestration, repo discovery, profile config | `config/profiles/*.yaml` |
| Global | Last session group (for `fob restore`) | `~/.local/share/fob/last-session.json` |

## `.fob/` Continuity Model

**Source files** — edit these directly:

| File | Role |
|------|------|
| `active-mission.md` | Current objective — singular, replace when focus changes |
| `standing-orders.md` | Stable repo policy — branch rules, operating constraints |
| `objectives.md` | Work inventory — in-progress, up-next, done |
| `mission-log.md` | Chronological log — decisions, stop points, what changed |

**Compiled artifact** — generated at launch, do not edit:

| File | Role |
|------|------|
| `.briefing` | All four files + runtime context compiled into one startup document |

`fob resume` prints the current briefing so you can inspect exactly what Claude will see.

## Commands

**Workspace:**

| Command | Description |
|---------|-------------|
| `fob` / `fob brief [repo]` | Auto-select current repo and launch |
| `fob brief --layout` | Launch using saved layout (explicit restore) |
| `fob multi` | Multi-select picker — open several repos as tabs |
| `fob restore` | Re-open last saved session group (`--show` to preview without launching) |
| `fob attach` | Re-attach to running `fob` session |
| `fob kill` | Terminate the `fob` session and all panes (warns first) |
| `fob init [repo]` | Initialize `.fob/` mission files in a repo |
| `fob resume` | Print current mission brief from `.fob/` |
| `fob test` | Run project tests |
| `fob audit` | Run project audit |
| `fob doctor` | Check and install dependencies |

**Visibility:**

| Command | Description |
|---------|-------------|
| `fob status` | Session, layout, branch, `.fob/` state |
| `fob status --all` | Compact table of all repos |
| `fob map` | Full state snapshot |
| `fob map --all` | Snapshot of all repos |
| `fob map --json` | Machine-readable state (single repo or `--all`) |

**Reset & Recovery:**

FOB is a persistent system. Every persistent system needs a clear escape hatch.

| Command | Description |
|---------|-------------|
| `fob reset` | Full reset — kills session, clears layout, deletes mission files (confirms first) |
| `fob reset --session` | Kill session only |
| `fob reset --layout` | Clear saved layout only |
| `fob reset --state` | Delete `.fob/` mission files only |
| `fob clear [--all]` | Delete saved layout (current repo or all) |

**Layout:**

Layout persistence is explicit and opt-in. Normal `fob brief` always generates a fresh layout.

| Command | Description |
|---------|-------------|
| `fob layout save` | Save current repo layout to `.fob/layout.json` |
| `fob layout load` | Restore saved layout (starts Zellij session) |
| `fob layout show` | Show saved layout metadata and path |
| `fob layout reset` | Delete saved layout for current repo |

Layout state lives in `.fob/layout.json` (metadata) and `.fob/layout.kdl` (Zellij KDL). Both are human-readable.

**Utility:**

| Command | Description |
|---------|-------------|
| `fob loadout` | Install and configure dev tools |
| `fob cheat` | Open keybinding reference |
| `fob install` | Symlink `fob` to `~/.local/bin` |

## Typical Session

First run (no existing session):

```
$ cd ~/Documents/GitHub/VideoFoundry
$ fob

  Brief: VideoFoundry
  session  creating   (fob)
  layout   fresh
  mission  implement multi-source audio mixing…

[Zellij opens — Claude pane starts, reads .fob/.briefing, continues]
```

Returning to an existing session:

```
$ fob

  Brief: VideoFoundry
  session  attaching  (fob)
  mission  implement multi-source audio mixing…

[Zellij attaches — workspace resumes exactly as left]
```

If the repo tab is already open, `fob` shows the picker to open a different repo instead of duplicating the tab.

## Inter-Repo Work

FOB handles multiple repos in two complementary ways:

**Multi-tab** — run `fob multi` from anywhere to get the multi-select picker. Tab to select multiple repos; each opens as a named tab in the same `fob` session. In multi-repo mode, Claude's working directory starts at `~/Documents/GitHub/` so it can navigate across repos freely.

**Peer context** — when multiple repos are opened together in a single `fob brief`, each repo's `.fob/.briefing` automatically includes the active mission and objectives of the other selected repos. Claude in each tab sees what the others are working on without any profile config required.

For persistent cross-repo awareness (across separate `fob brief` invocations), configure peers in a profile:

```yaml
claude:
  peers:
    - controlplane   # always pulls ControlPlane's mission + objectives into this briefing
```

**Session groups** — every `fob brief` auto-saves the selected repos as the "last group". Re-open the exact same set with:

```bash
fob restore             # re-open last saved group (briefings regenerated fresh)
fob restore --show      # preview what would be restored without launching
```

**Cross-repo visibility:**

```bash
fob status --all        # one-line summary of every repo: tab, layout, branch, mission
fob map --all           # detailed snapshot of every repo
fob map --all --json    # machine-readable — useful for Control Plane delegation
```

## Profiles (Optional)

Repos are auto-discovered — no YAML needed for basic use. Create `config/profiles/<name>.yaml` to configure custom Claude context files, peer repo awareness, or non-default helper commands.

See [docs/profiles.md](docs/profiles.md).

## Further Reading

- [docs/architecture.md](docs/architecture.md) — launcher flow, session model, layout persistence internals
- [docs/profiles.md](docs/profiles.md) — profile format and optional configuration
- [docs/guardrails.md](docs/guardrails.md) — safe branch practices and Claude operating model
