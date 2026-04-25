# OperatorConsole — Daily Use

Practical notes for repeated, reliable use.

---

## Normal Startup

Start the WorkStation stack (SwitchBoard must be healthy before any task):

```bash
cd ~/Documents/GitHub/WorkStation
./scripts/up.sh
```

`up.sh` starts SwitchBoard, optionally Plane, and all OperationsCenter watcher
roles (including intake). No manual worker start needed.

Confirm readiness:

```bash
console status
console providers
```

`console status` checks SwitchBoard health, OperationsCenter reachability,
watcher role status, and the most recent run.
`console providers` shows which backend binaries are installed and available.

Expected: SwitchBoard OK, OperationsCenter OK, intake running, at least one lane binary available.

---

## Submitting a Task

**Interactive wizard (recommended):**

```bash
console run
```

Prompts for repo → task type → goal, then writes to `~/.console/queue/`.
OperationsCenter's intake role picks it up, elaborates it using `.console/`
context and recent commits, and drives execution.

**Non-interactive fast path:**

```bash
console run --goal "Fix the login bug" --task-type bug --repo MyRepo
```

**Check what's queued:**

```bash
console queue
```

---

## What Happens After Submission

1. `console run` writes `~/.console/queue/<uuid>.json`
2. **intake** role detects the file (inotifywait or 10s poll)
3. intake loads `.console/task.md`, `.console/backlog.md`, recent commits from the target repo
4. intake elaborates the raw goal into a scoped `PlanningContext`
5. planning → SwitchBoard routing → adapter execution
6. Result written to `~/.console/operations_center/runs/<run_id>/`
7. Queue file deleted on success (left on disk if intake fails)

---

## Watcher Roles

OperationsCenter runs several background watcher roles. `up.sh` starts them all;
`down.sh` stops them.

```bash
console workers status     # check all roles
console workers start      # start (if not already running)
console workers stop       # stop all roles
console workers restart    # restart
```

The `intake` role is the one that processes your queue submissions. The other
roles (`goal`, `test`, `improve`, `propose`, `review`, `spec`) are the
autonomous planning loop.

---

## Inspecting Runs

**Most recent run:**

```bash
console last
```

**All fields + recent run list:**

```bash
console last --all
```

**List of recent runs (newest first):**

```bash
console runs
```

**Limit to last 5:**

```bash
console runs --limit 5
```

**Machine-readable:**

```bash
console last --json
console runs --json
```

**Browse artifact files directly:**

```bash
ls ~/.console/operations_center/runs/
ls ~/.console/operations_center/runs/<run_id>/
```

Each run directory contains:

```
proposal.json          TaskProposal
decision.json          LaneDecision
execution_request.json ExecutionRequest
result.json            ExecutionResult
run_metadata.json      run id, lane, status, timestamp
```

---

## Exit Codes

`console run` returns a specific exit code to allow scripting:

| Code | Meaning |
|------|---------|
| 0 | Task queued successfully |
| 1 | Cancelled, missing input, or unknown repo/type |

Execution outcomes are recorded in run artifacts — `console last` shows the result.

---

## Autonomy Surfaces

There are two separate autonomy surfaces. They are not interchangeable.

| | `console cycle` | OperationsCenter autonomy cycle |
|---|---|---|
| **What it does** | Observes the repo, proposes one task, delegates it for execution | Runs the OperationsCenter planning loop — creates Plane board tasks |
| **Executes code?** | Yes — goes through the full pipeline to an adapter | No direct execution; produces Plane task proposals |
| **Creates Plane tasks?** | No | Yes |
| **Stops automatically?** | Yes — one cycle, then exits | Yes — one cycle per invocation |
| **When to use** | You want one self-driven code change executed now | You want the planner to queue work on the board |

Run `console cycle` for immediate local execution.
Run `python -m operations_center.entrypoints.autonomy_cycle.main` (from the OperationsCenter repo) for board-driven planning.

---

## Artifact Behavior

Each run gets a unique UUID-based run ID. Directories never overwrite each other.

Failed runs remain as `failure_category=backend_error` or `partial` directories. They do not affect subsequent runs.

`console last` and `console runs` sort by `written_at` timestamp in the metadata — newest run is always correct regardless of directory naming.

---

## Cleanup

Runs accumulate indefinitely. To prune old runs:

```bash
console clean --keep 10    # keep 10 most recent, delete the rest
console clean --dry-run    # preview what would be deleted
```

Or manually:

```bash
ls -lt ~/.console/operations_center/runs/     # newest first
rm -rf ~/.console/operations_center/runs/<run_id>
```

Queue files that failed intake are left at `~/.console/queue/` — inspect and
delete manually:

```bash
console queue
rm ~/.console/queue/<id>.json
```

---

## Failure Recovery

**Intake not picking up tasks:**
```bash
console workers status     # check if intake is running
console workers restart    # restart all roles
```

**SwitchBoard unreachable:**
```bash
console status             # confirm
cd ~/Documents/GitHub/WorkStation && ./scripts/up.sh
```

**Run failed (backend not installed):**
`failure_category=backend_error` is expected when a backend binary (`kodo`,
`aider`, etc.) is not installed. The intake and planning pipeline ran correctly —
only the final adapter invocation failed.

---

## Daily Regression Path

Run these in order to confirm the system is working:

```bash
console status                        # stack + OperationsCenter + watchers + binaries
console providers                     # backend binary readiness
console run --goal "smoke test" \
            --task-type chore \
            --repo OperatorConsole    # submit to queue
console queue                         # confirm it's queued
console last                          # confirm a run was recorded (after intake picks it up)
```

---

## Full End-to-End Validation

```bash
console demo
```

Runs all six steps: preflight → stack → health → route → planning → execution.

---

## Known Limits

| Limit | Detail |
|---|---|
| Single machine only | No distributed or multi-user support |
| intake requires inotify-tools | Install with `sudo apt install inotify-tools`; falls back to 10s polling without it |
| Backend binary required for execution | Execution without `kodo`/`aider` records `backend_error` — not a pipeline bug |
| SwitchBoard must be running | All routing calls fail if WorkStation stack is down |
| No run search | `console runs` shows recent runs by time; no filtering by status or goal |
| Partial runs counted | `console runs` shows partial artifacts alongside complete runs |
| Queue files persist on intake failure | Inspect `~/.console/queue/` and remove manually |
