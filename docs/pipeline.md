# OperatorConsole Pipeline Commands

OperatorConsole is the primary operator interface to the system. Tasks are
submitted to a local queue; OperationsCenter's intake role picks them up,
elaborates them, and drives execution through SwitchBoard.

---

## Flow

```
console run  →  ~/.console/queue/<id>.json  →  intake role  →  planning  →  SwitchBoard  →  adapter
```

OperatorConsole submits and steps back. OperationsCenter owns the rest.

---

## Commands

### `console run` — submit a task

Interactive wizard that writes a task to the local queue. OperationsCenter's
intake role picks it up, adds context from the repo's `.console/` files and
recent commits, then drives the full planning → execution pipeline.

```bash
console run                                         # interactive wizard
console run --goal "Fix the login bug" \
            --task-type bug \
            --repo MyRepo                           # non-interactive fast path
console run --goal "..." --json                     # machine-readable output
```

**Wizard steps:**
1. **Repo** — auto-detected from cwd, or picker if outside a known repo
2. **Task type** — fzf selector (bug / feature / refactor / docs / lint / test / chore / investigation)
3. **Goal** — free text: what's the problem?

**Flags:**

| Flag | Default | Description |
|---|---|---|
| `--goal TEXT` | prompted | Raw goal description |
| `--task-type TYPE` | prompted | Task classification |
| `--repo NAME` | auto from cwd | Repo name under ~/Documents/GitHub/ |
| `--priority LEVEL` | `normal` | `low` / `normal` / `high` |
| `--json` | false | Machine-readable output |

**Example output:**

```
  console run — submit task to queue

  · repo: MyRepo  (auto-detected from cwd)

  Task type:
  > bug

  What's the problem?
  > The login form doesn't validate empty passwords

  ✓ queued  MyRepo  bug  'The login form doesn't validate empty passwords'
  · queue: ~/.console/queue/3a8f…json
  · OperationsCenter intake will pick this up and elaborate it
```

**Queue file** lives at `~/.console/queue/<uuid>.json` until intake processes it.
Inspect pending tasks with `console queue`.

---

### `console queue` — inspect pending tasks

Shows tasks waiting in the local queue for intake pickup.

```bash
console queue           # list pending tasks
console queue --json    # machine-readable
```

**Example output:**

```
  console queue — pending tasks (2)

  3a8f…  bug        MyRepo    The login form doesn't validate empty passwords
  b2c1…  feature    MyRepo    Add dark mode toggle to settings page
```

---

### `console workers` — watcher lifecycle

Start, stop, or check the OperationsCenter watcher roles (including intake).
Delegates to PlatformDeployment's shim — OperatorConsole never touches OperationsCenter
directly.

```bash
console workers status     # show role status
console workers start      # start all roles
console workers stop       # stop all roles
console workers restart    # restart all roles
```

Watchers are also started automatically by `./scripts/up.sh` in PlatformDeployment and
stopped by `./scripts/down.sh`.

---

### `console last` — inspect the most recent run

Shows a concise summary of the most recent execution run.

```bash
console last               # most recent run summary
console last --all         # summary + list of recent runs
console last --json        # machine-readable JSON
```

**No runs found:** If no runs exist, `console last` returns exit code 1 and
suggests submitting a task with `console run`.

---

### `console status` — system readiness

Shows SwitchBoard health, OperationsCenter availability, lane binary status,
watcher role status, and the most recent run.

```bash
console status             # system readiness overview
console status --json      # machine-readable
```

---

## Artifact location

All run artifacts are written by OperationsCenter to:

```
~/.console/operations_center/runs/<run_id>/
  proposal.json
  decision.json
  execution_request.json
  result.json
  run_metadata.json
```

See [docs/operator/run-artifacts.md](https://github.com/ProtocolWarden/OperationsCenter/blob/main/docs/operator/run-artifacts.md) in the OperationsCenter repo for full field reference.

---

## Quick reference

```bash
console run                  # submit a task (interactive)
console queue                # inspect pending queue
console workers status       # check watcher roles
console last                 # inspect last completed run
console last --all           # inspect + history
console status               # full system health
console demo                 # full architecture validation
console providers            # lane readiness detail
```

---

## Known limitations

- Intake elaboration uses `.console/` context files and recent git commits — no
  live LLM call at submission time. The adapters do the deep work at execution.
- Queue files are left on disk if intake fails — inspect `~/.console/queue/` and
  remove manually if needed.
- `console status` lane checks are binary (installed / not installed); they do not
  verify API credentials or model access.
- Run history is stored locally in `~/.console/`; no cross-machine sync.
