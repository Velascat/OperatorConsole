# Guardrails

## Safe Branch Practices

FOB warns when launched from `main` or `master`. This is not a hard block — it's a reminder.

Claude's `standing-orders.md` (in each repo's `.fob/`) enforces the actual discipline:
- Claude will not commit to protected branches
- Claude will stop and ask for a working branch before making changes

Create a working branch before launching:
```bash
cd <repo>
git checkout -b feature/<description>
fob
```

## Intended Claude Usage Model

Claude operates as an AI operator inside the workspace. The expected loop:

1. **Read mission files** — Claude reads `.fob/` to understand current context
2. **Summarize plan** — Claude describes what it intends to do before any edits
3. **Edit** — targeted changes, not rewrites
4. **Validate** — run `fob test` or `fob audit`
5. **Summarize result** — what changed, what passed or failed
6. **Update mission files** — Claude updates `.fob/objectives.md` and `.fob/mission-log.md`

This loop is described in `.fob/standing-orders.md` in each repo.

## Helper Commands

Prefer wrapper commands over raw shell sequences:

| Command | Replaces |
|---------|---------|
| `fob test` | `pytest -x -v` / `npm test` / etc. |
| `fob audit` | `ruff check` / `tsc --noEmit` / custom lint |
| `fob status` | `git status` + session / layout / branch info |
| `fob map` | full structured state snapshot |
| `fob resume` | reading `.fob/` files manually |
| `fob reset` | manually killing sessions and deleting state files |
| `fob clear` | deleting `.fob/layout.json` + `.fob/layout.kdl` manually |
| `fob cheat` | looking up keybindings |

These are stable entrypoints. Claude should use them rather than constructing long shell pipelines.

## Filesystem Scope

Intended writable scope for Claude:
- The configured `repo_root` and its children
- `<repo>/.fob/` for mission file updates
- `/tmp/` for transient files

Claude should not write outside `repo_root` without explicit operator confirmation.

## Claude Process Lifecycle

Understanding what happens to Claude when Zellij state changes:

| Action | Claude process |
|--------|---------------|
| Close terminal window | Keeps running — Zellij session stays alive in background |
| Detach (Ctrl+o d) | Keeps running — session persists, re-attach with `fob attach` |
| Kill Claude pane (Ctrl+p x) | Process dies — that tab's Claude is gone |
| `fob kill` | Everything dies — session and all panes killed (confirms first) |

**Closing the terminal does not kill Claude.** Zellij sessions persist as background processes. The panes — Claude, shell, lazygit — keep running. Re-attach at any time with:
```bash
fob attach        # re-attach to the running fob session
fob               # from inside a known repo: adds/re-opens that repo's tab
```

**Key point:** Even if Claude is killed, `claude --continue` on the next `fob brief` resumes the conversation from where it left off. Conversation history is preserved by Claude Code; only work that was mid-execution is lost.

Recovery path after an accidental kill: `fob brief` restores everything.

### Letting Claude Work Autonomously

To kick off a task and walk away:

1. Give Claude instructions in the pane
2. Detach: `Ctrl+o d` (or just close the terminal — same result)
3. Come back later: `fob attach` or `fob` from the repo

Claude continues working. When you re-attach, the pane shows exactly what happened.

For cross-repo autonomous work (e.g. Claude on ControlPlane monitoring FOB state), the pattern is:
- Run `fob brief controlplane fob` to open both repos in tabs
- Give Claude in the ControlPlane tab explicit instructions and a clear stopping condition
- Detach — both Claude instances keep running independently

## What Is Not Automated

By design, the following require explicit operator action:

- Pushing to remote branches
- Creating pull requests
- Merging branches
- Deploying / releasing
- Modifying CI/CD configuration

These are human-in-the-loop checkpoints. FOB is a local workspace, not a deployment pipeline.
