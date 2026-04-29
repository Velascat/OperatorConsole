# Using the aider_local Lane

The `aider_local` lane runs tasks locally via Aider + Ollama. It is free, CPU-only, and designed for low-risk tasks like lint fixes and small edits.

## Prerequisites

1. Ollama running at `http://localhost:11434`
2. `qwen2.5-coder:3b` pulled: `ollama pull qwen2.5-coder:3b`
3. WorkStation lane configured and enabled (see WorkStation docs)

Check readiness:

```bash
cd ../WorkStation
python -m workstation_cli lane doctor aider_local
```

## Submitting a task to the aider_local lane

```bash
console run --lane aider_local --goal "Fix the ruff lint errors" --task-type lint --repo MyRepo
```

The `--lane` flag is a **hint** to OperationsCenter. SwitchBoard still makes the final routing decision — if the lane is unavailable, it will fall back to `claude_cli`.

### Non-interactive

```bash
console run \
  --lane aider_local \
  --goal "Fix the ruff lint errors in src/api.py" \
  --task-type lint \
  --repo MyRepo \
  --priority normal
```

### Interactive (wizard)

```bash
console run
```

Lane selection is not shown in the interactive wizard — use `--lane` as a flag if you want to hint a specific lane.

## Valid lane values

| Value | Description |
|-------|-------------|
| `aider_local` | CPU-only Aider via local Ollama |
| `claude_cli` | Cloud-hosted Claude (default for most tasks) |
| `codex_cli` | Codex routing path |

## What happens after submission

1. Task JSON written to `~/.console/queue/<id>.json` with `lane_hint: aider_local`
2. OperationsCenter intake picks up the task
3. SwitchBoard evaluates routing — if `aider_local` matches and is available, it selects it
4. `AiderLocalBackendAdapter` runs aider against the repo workspace
5. Result appears in `console runs` / `console last`

## Checking results

```bash
console last           # most recent run
console runs           # list recent runs
console last --json    # machine-readable
```
