# OperatorConsole Cockpit Commands

OperatorConsole is the primary operator interface to the system. All common
operations are available without touching OperationsCenter internals or artifact
directories directly.

---

## Commands

### `console run` — run a task

Triggers a full execution: planning → SwitchBoard routing → adapter → result.

```bash
console run --goal "Refresh the README summary"
console run --goal "Fix lint errors" --repo-key myrepo --clone-url https://github.com/org/repo.git
console run --goal "Update docs" --task-type documentation
console run --goal "..." --dry-run    # planning only, no execution
console run --goal "..." --json       # machine-readable output
```

**Flags:**

| Flag | Default | Description |
|---|---|---|
| `--goal TEXT` | prompted | Task goal (required) |
| `--task-type TYPE` | `documentation` | Task classification |
| `--repo-key KEY` | `default` | Repository key |
| `--clone-url URL` | placeholder | Repository clone URL |
| `--task-branch BRANCH` | auto-generated | Git branch for this run |
| `--dry-run` | false | Planning only, no adapter execution |
| `--json` | false | Machine-readable output |

**Example output:**

```
  console run — delegating task to OperationsCenter

  [OperatorConsole] goal='Refresh README summary'  type=documentation  repo=default
  ── planning
  [OperationsCenter] proposal created — id=a1b2c3d4…
  [SwitchBoard] selected lane=claude_cli  backend=kodo
  [Adapter] executing  lane=claude_cli  backend=kodo
  ⚠ Backend ran but failed — status=failed  category=backend_error
  · This is expected when the backend binary is not installed on this machine.

  Run ID     abc123...
  Artifacts  ~/.console/operations_center/runs/abc123.../
```

**Artifacts:** Every run persists all four canonical contracts to
`~/.console/operations_center/runs/<run_id>/`. See `console last` to inspect.

---

### `console last` — inspect the most recent run

Shows a concise summary of the most recent execution run from artifacts.

```bash
console last               # most recent run summary
console last --all         # summary + list of recent runs
console last --json        # machine-readable JSON
```

**Example output:**

```
  console last — most recent execution run

  Run ID    abc123ef-...
  Status    success
  Executed  yes
  Lane      claude_cli  → kodo
  Written   2026-04-24 10:00:00

  Task
    goal      Refresh README summary
    type      documentation
    repo      default

  · artifacts: ~/.console/operations_center/runs/abc123.../
```

**No runs found:** If no runs exist, `console last` returns exit code 1 and suggests
running `console run` or `console demo`.

---

### `console status` — system readiness

Shows SwitchBoard health, OperationsCenter availability, lane binary status, and
a summary of the most recent run.

```bash
console status             # system readiness overview
console status --json      # machine-readable
console status --repo      # old repo/session state view (branch, layout, .console/)
console status --all       # compact table of all repos
```

**Example output:**

```
  console status — system readiness

  SwitchBoard            OK  http://localhost:20401/health
  OperationsCenter           OK  ~/Documents/GitHub/OperationsCenter

  Lanes
    claude_cli           available  (claude)
    codex_cli            available  (codex)
    kodo                 available  (kodo)
    aider_local          unavailable  (aider)

  Last run
    id      abc123ef-...
    status  success
    lane    claude_cli
    goal    Refresh README summary
    at      2026-04-24 10:00:00
```

Returns exit code 1 if SwitchBoard or OperationsCenter are not reachable.

---

## Artifact location

All run artifacts are in:

```
~/.console/operations_center/runs/<run_id>/
  proposal.json
  decision.json
  execution_request.json
  result.json
  run_metadata.json
```

See `docs/operator/run-artifacts.md` (OperationsCenter repo) for full field reference.

---

## Quick reference

```bash
console run --goal "..."     # trigger execution
console last                 # inspect last run
console last --all           # inspect + history
console status               # system health + last run
console demo                 # full architecture validation
console providers            # lane readiness detail
```

---

## Known limitations

- `console run` uses placeholder `clone-url` and `repo-key` by default — the
  execution boundary is real but the adapter won't find a real repo to clone
  unless you provide `--clone-url`.
- Lane binary failures (e.g. `kodo` or `aider` not installed) produce a canonical
  `ExecutionResult(success=False, failure_category=backend_error)` — the pipeline
  itself ran correctly.
- `console status` lane checks are binary (installed / not installed); they do not
  verify API credentials or model access.
- Run history is stored locally in `~/.console/`; no cross-machine sync.
