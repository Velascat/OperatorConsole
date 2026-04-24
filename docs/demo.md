# fob demo — End-to-End Architecture Verification

`fob demo` proves the full path from operator to execution result.

---

## What it does

Runs six sequential steps across the full stack:

```
1. Preflight       repos present, config bootstrapped
2. Stack           WorkStation Docker stack healthy
3. Health          SwitchBoard reachable at /health
4. Route           SwitchBoard returns a real LaneDecision
5. Planning        ControlPlane builds TaskProposal, routes through SwitchBoard
6. Execution       ControlPlane runs the selected backend adapter
```

Canonical run artifacts are written to `~/.fob/control_plane/runs/<run_id>/`
by the execute entrypoint's `RunArtifactWriter`. Use `fob last` to inspect them.

---

## Prerequisites

```bash
# From WorkStation:
./scripts/up.sh          # start the full stack (SwitchBoard must be healthy)
```

ControlPlane and SwitchBoard repos must be at:

```
~/Documents/GitHub/ControlPlane/
~/Documents/GitHub/SwitchBoard/
~/Documents/GitHub/WorkStation/
```

---

## Run the demo

```bash
fob demo
```

Skip the stack start (if already running):

```bash
fob demo --no-start
```

Machine-readable output:

```bash
fob demo --json
```

---

## What success looks like

```
  fob demo — end-to-end architecture validation

── 1 · Preflight ─────────────────────────────────────
  ✓ WorkStation: ~/Documents/GitHub/WorkStation
  ✓ SwitchBoard: ~/Documents/GitHub/SwitchBoard
  ✓ ControlPlane: ~/Documents/GitHub/ControlPlane
  ✓ .env present
  ✓ workstation endpoints config present

── 2 · Stack ─────────────────────────────────────────
  ✓ WorkStation stack ready

── 3 · Health ────────────────────────────────────────
  ✓ SwitchBoard health: ok

── 4 · Route Selection ───────────────────────────────
  ✓ lane=claude_cli backend=kodo

── 5 · Planning ──────────────────────────────────────
  ✓ proposal=<id> task=fob-demo-worker lane=claude_cli backend=kodo rule=...

── 6 · Execution ─────────────────────────────────────
  · lane=claude_cli  backend=kodo
  ✓ Backend executed successfully — status=success
  · artifacts: ~/.fob/control_plane/runs/<run_id>/

── Summary ───────────────────────────────────────────
  PASS preflight
  PASS stack
  PASS health
  PASS route
  PASS planning
  PASS execution      status=success executed=True

  ✓ Full end-to-end path verified
  · artifacts: ~/.fob/control_plane/runs/<run_id>/
  · run `fob last` to inspect
```

---

## Artifact location

Artifacts are the canonical Phase 7 run artifacts written by `RunArtifactWriter`:

```
~/.fob/control_plane/runs/<run_id>/
  proposal.json
  decision.json
  execution_request.json
  result.json
  run_metadata.json
```

```bash
fob last                              # inspect most recent run
fob last --json                       # machine-readable
ls ~/.fob/control_plane/runs/         # list all runs
```

---

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Step 1 fails (WorkStation not found) | Repo not at expected path | Clone WorkStation to `~/Documents/GitHub/WorkStation` |
| Step 3 fails (HTTP 0) | SwitchBoard not running | Run `./scripts/up.sh` from WorkStation |
| Step 5 fails (exit 1) | ControlPlane venv missing | `cd ControlPlane && pip install -e .` |
| Step 6 — backend failure | Backend binary not installed | Install `kodo` or `aider`; result is still canonical |
| Step 6 — policy skipped | Policy gate blocked the task | Check SwitchBoard policy config |

Step 6 returning `success=False` with `failure_category=backend_error` is **expected** when
the backend binary is not installed on the current machine. The execution boundary is still
real — the adapter ran and returned a canonical `ExecutionResult`.

---

## Contract chain

The demo exercises the full contract chain:

```
PlanningContext
    → build_proposal()     → TaskProposal        (proposal.json)
    → SwitchBoard /route   → LaneDecision         (decision.json)
    → ExecutionRequestBuilder → ExecutionRequest  (execution_request.json)
    → backend adapter      → ExecutionResult      (result.json)
```

All four canonical contracts (`TaskProposal`, `LaneDecision`, `ExecutionRequest`,
`ExecutionResult`) are exercised. No mocks in the live path.
