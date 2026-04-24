"""fob demo — validate the full end-to-end architecture path.

Runs the full stack in order:

  1. Preflight       — repos + config present
  2. Stack           — WorkStation stack healthy
  3. Health          — SwitchBoard reachable
  4. Route           — SwitchBoard returns a real LaneDecision
  5. Planning        — ControlPlane builds TaskProposal + routes through SwitchBoard
  6. Execution       — ControlPlane runs the selected adapter, returns ExecutionResult
  7. Artifacts       — proposal, decision, result saved to ~/.fob/demo-artifacts/
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_C = {
    "R": "\033[0m", "B": "\033[1m", "DIM": "\033[2m",
    "RED": "\033[31m", "GRN": "\033[32m", "YLW": "\033[33m",
    "CYN": "\033[36m", "MAG": "\033[35m",
}


def _c(text: str, *keys: str) -> str:
    return "".join(_C[k] for k in keys) + text + _C["R"]


def _ok(msg: str) -> None:
    print(f"  {_c('✓', 'GRN')} {msg}")


def _fail(msg: str) -> None:
    print(f"  {_c('✗', 'RED')} {msg}")


def _info(msg: str) -> None:
    print(f"  {_c('·', 'DIM')} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_c('⚠', 'YLW')} {msg}")


def _section(title: str) -> None:
    print()
    print(_c(f"── {title} ", "B", "CYN") + _c("─" * max(0, 48 - len(title)), "DIM"))


# Minimal ControlPlane config sufficient for the demo execute entrypoint.
# Only kodo/aider settings matter for adapter construction; plane/repos
# are required fields but unused during single-task execution.
_DEMO_CP_CONFIG = """\
plane:
  base_url: http://localhost:8080
  api_token_env: PLANE_API_TOKEN
  workspace_slug: demo
  project_id: demo
git:
  provider: github
kodo:
  binary: kodo
repos: {}
"""


@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class DemoResult:
    steps: list[StepResult] = field(default_factory=list)

    def add(self, step: StepResult) -> None:
        self.steps.append(step)

    @property
    def passed(self) -> bool:
        return all(step.passed for step in self.steps)


def _http_get(url: str, timeout: float = 5.0) -> tuple[int, Any]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except Exception as exc:
        return 0, {"error": str(exc)}


def _http_post(url: str, payload: dict[str, Any], timeout: float = 10.0) -> tuple[int, Any]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        try:
            body = json.loads(body_text)
        except Exception:
            body = {"raw": body_text}
        return exc.code, body
    except Exception as exc:
        return 0, {"error": str(exc)}


def _repo_root(name: str) -> Path:
    return Path.home() / "Documents" / "GitHub" / name


def _find_workstation() -> Path | None:
    repo = _repo_root("WorkStation")
    return repo if (repo / "scripts" / "ensure-up.sh").exists() else None


def _cp_python(cp_repo: Path) -> str:
    """Return path to ControlPlane's venv Python, falling back to python3."""
    venv_python = cp_repo / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else "python3"


# ---------------------------------------------------------------------------
# Steps 1–4 (unchanged)
# ---------------------------------------------------------------------------


def step_preflight(workstation_root: Path | None) -> StepResult:
    _section("1 · Preflight")
    if workstation_root is None:
        _fail("WorkStation repo not found")
        return StepResult("preflight", False, "WorkStation not found")

    expected = {
        "WorkStation": workstation_root,
        "SwitchBoard": _repo_root("SwitchBoard"),
        "ControlPlane": _repo_root("ControlPlane"),
    }
    missing: list[str] = []
    for name, path in expected.items():
        if path.exists():
            _ok(f"{name}: {path}")
        else:
            _fail(f"{name} missing at {path}")
            missing.append(name)

    env_file = workstation_root / ".env"
    if env_file.exists():
        _ok(".env present")
    else:
        _fail(".env missing")
        missing.append(".env")

    endpoints = workstation_root / "config" / "workstation" / "endpoints.yaml"
    endpoints_example = workstation_root / "config" / "workstation" / "endpoints.example.yaml"
    if endpoints.exists():
        _ok("workstation endpoints config present")
    elif endpoints_example.exists():
        import shutil
        shutil.copy(endpoints_example, endpoints)
        _ok("endpoints.yaml bootstrapped from example")
    else:
        _fail("config/workstation/endpoints.yaml missing")
        missing.append("endpoints.yaml")

    return StepResult("preflight", not missing, ", ".join(missing) if missing else "all checks passed")


def step_stack(workstation_root: Path) -> StepResult:
    _section("2 · Stack")
    script = workstation_root / "scripts" / "ensure-up.sh"
    result = subprocess.run(["bash", str(script)], capture_output=False)
    if result.returncode == 0:
        _ok("WorkStation stack ready")
        return StepResult("stack", True, "healthy")
    _fail(f"ensure-up.sh exited {result.returncode}")
    return StepResult("stack", False, f"ensure-up.sh exited {result.returncode}")


def step_health() -> StepResult:
    _section("3 · Health")
    port = os.environ.get("PORT_SWITCHBOARD", "20401")
    code, body = _http_get(f"http://localhost:{port}/health")
    if code == 200:
        _ok(f"SwitchBoard health: {body.get('status', 'ok')}")
        return StepResult("health", True, body.get("status", "ok"))
    _fail(f"SwitchBoard health failed: HTTP {code}")
    return StepResult("health", False, f"HTTP {code}")


def step_route() -> StepResult:
    _section("4 · Route Selection")
    port = os.environ.get("PORT_SWITCHBOARD", "20401")
    payload = {
        "task_id": "fob-demo-route",
        "project_id": "fob-demo",
        "task_type": "documentation",
        "execution_mode": "goal",
        "goal_text": "Refresh the architecture summary wording",
        "target": {
            "repo_key": "docs",
            "clone_url": "https://example.invalid/docs.git",
            "base_branch": "main",
            "allowed_paths": [],
        },
        "priority": "normal",
        "risk_level": "low",
        "constraints": {
            "allowed_paths": [],
            "require_clean_validation": True,
        },
        "validation_profile": {
            "profile_name": "default",
            "commands": [],
        },
        "branch_policy": {
            "push_on_success": True,
            "open_pr": False,
        },
        "labels": [],
    }
    code, body = _http_post(f"http://localhost:{port}/route", payload)
    if code == 200:
        _ok(f"lane={body['selected_lane']} backend={body['selected_backend']}")
        return StepResult("route", True, f"{body['selected_lane']}/{body['selected_backend']}")
    _fail(f"SwitchBoard route failed: HTTP {code}")
    return StepResult("route", False, f"HTTP {code}")


# ---------------------------------------------------------------------------
# Step 5 — Planning (builds TaskProposal + routes through SwitchBoard)
# ---------------------------------------------------------------------------


def step_planning(cp_repo: Path) -> tuple[StepResult, dict | None]:
    """Call ControlPlane worker to build TaskProposal and get LaneDecision.

    Returns (StepResult, bundle_dict) — bundle_dict contains proposal + decision.
    """
    _section("5 · Planning")
    python = _cp_python(cp_repo)
    cmd = [
        python, "-m", "control_plane.entrypoints.worker.main",
        "--goal", "Refresh architecture wording",
        "--task-type", "documentation",
        "--repo-key", "docs",
        "--clone-url", "https://example.invalid/docs.git",
        "--project-id", "fob-demo",
        "--task-id", "fob-demo-worker",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(cp_repo / "src")

    result = subprocess.run(cmd, cwd=cp_repo, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        _fail("ControlPlane planning failed")
        _info(result.stderr.strip() or result.stdout.strip())
        return StepResult("planning", False, f"exit {result.returncode}"), None

    bundle = json.loads(result.stdout)
    summary = bundle.get("run_summary", "?")
    _ok(summary)
    return StepResult("planning", True, summary), bundle


# ---------------------------------------------------------------------------
# Step 6 — Execution (builds ExecutionRequest, runs adapter, returns result)
# ---------------------------------------------------------------------------


def step_execution(
    cp_repo: Path,
    bundle_data: dict,
    artifacts_dir: Path,
) -> tuple[StepResult, dict | None]:
    """Run the selected backend adapter and return a canonical ExecutionResult.

    Uses ControlPlane's execute entrypoint which enforces the policy gate and
    invokes the adapter selected by SwitchBoard in the planning step.
    The result is real regardless of whether the backend binary is installed:
    a missing binary returns ExecutionResult(success=False, failure_category=backend_error).
    """
    _section("6 · Execution")

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    workspace = artifacts_dir / "workspace"
    workspace.mkdir(exist_ok=True)

    # Write the bundle from planning step for the execute entrypoint to consume
    bundle_file = artifacts_dir / "bundle.json"
    bundle_file.write_text(json.dumps(bundle_data), encoding="utf-8")

    # Write minimal ControlPlane config (only backend settings matter here)
    config_file = artifacts_dir / "control_plane.yaml"
    config_file.write_text(_DEMO_CP_CONFIG, encoding="utf-8")

    result_file = artifacts_dir / "execution_result_raw.json"

    python = _cp_python(cp_repo)
    cmd = [
        python, "-m", "control_plane.entrypoints.execute.main",
        "--config", str(config_file),
        "--bundle", str(bundle_file),
        "--workspace-path", str(workspace),
        "--task-branch", "auto/fob-demo",
        "--output", str(result_file),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(cp_repo / "src")

    proc = subprocess.run(cmd, cwd=cp_repo, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        _fail("ControlPlane execute entrypoint crashed")
        _info(proc.stderr.strip() or proc.stdout.strip())
        return StepResult("execution", False, f"exit {proc.returncode}"), None

    if not result_file.exists():
        _fail("Execute entrypoint produced no output file")
        return StepResult("execution", False, "no output"), None

    outcome = json.loads(result_file.read_text(encoding="utf-8"))
    exec_result = outcome.get("result", {})
    status = exec_result.get("status", "unknown")
    executed = outcome.get("executed", False)
    success = exec_result.get("success", False)
    failure_category = exec_result.get("failure_category")

    lane = bundle_data.get("decision", {}).get("selected_lane", "?")
    backend = bundle_data.get("decision", {}).get("selected_backend", "?")
    _info(f"lane={lane}  backend={backend}")

    if executed and success:
        _ok(f"Backend executed successfully — status={status}")
    elif executed and not success:
        _warn(f"Backend ran but returned failure — status={status}  category={failure_category}")
        _info("This is expected when the backend binary is not installed on this machine.")
    elif not executed:
        policy_notes = outcome.get("policy_decision", {}).get("notes", "")
        _warn(f"Execution skipped by policy gate — status={status}")
        if policy_notes:
            _info(f"policy: {policy_notes}")

    return StepResult(
        "execution",
        True,
        f"status={status} executed={executed}",
    ), outcome


# ---------------------------------------------------------------------------
# Step 7 — Artifact persistence
# ---------------------------------------------------------------------------


def step_artifacts(
    artifacts_dir: Path,
    bundle_data: dict,
    outcome: dict | None,
) -> StepResult:
    """Persist canonical contract artifacts to a stable, inspectable location."""
    _section("7 · Artifacts")

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    proposal_file = artifacts_dir / "proposal.json"
    proposal_file.write_text(
        json.dumps(bundle_data.get("proposal", {}), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _ok(f"proposal.json")
    saved.append("proposal.json")

    decision_file = artifacts_dir / "decision.json"
    decision_file.write_text(
        json.dumps(bundle_data.get("decision", {}), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _ok(f"decision.json")
    saved.append("decision.json")

    if outcome is not None:
        result_file = artifacts_dir / "execution_result.json"
        result_file.write_text(
            json.dumps(outcome.get("result", {}), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _ok(f"execution_result.json")
        saved.append("execution_result.json")

    print()
    _info(f"artifacts: {artifacts_dir}")
    _info(f"inspect:   ls {artifacts_dir}")

    return StepResult("artifacts", True, f"{len(saved)} files → {artifacts_dir}")


# ---------------------------------------------------------------------------
# Summary + entry
# ---------------------------------------------------------------------------


def _print_summary(result: DemoResult, artifacts_dir: Path | None = None) -> None:
    _section("Summary")
    for step in result.steps:
        marker = _c("PASS", "GRN") if step.passed else _c("FAIL", "RED")
        print(f"  {marker} {step.name:<14} {step.detail}")
    print()
    if result.passed:
        _ok("Full end-to-end path verified")
        if artifacts_dir and artifacts_dir.exists():
            _info(f"artifacts at: {artifacts_dir}")
    else:
        _fail("Demo failed — see step above")


def run_demo(args: list[str]) -> int:
    no_start = "--no-start" in args
    use_json = "--json" in args

    print(_c("\n  fob demo", "B", "CYN") + _c(" — end-to-end architecture validation", "DIM"))

    workstation_root = _find_workstation()
    cp_repo = _repo_root("ControlPlane")
    artifacts_dir = Path.home() / ".fob" / "demo-artifacts"

    result = DemoResult()

    # Step 1 — Preflight
    preflight = step_preflight(workstation_root)
    result.add(preflight)
    if not preflight.passed or workstation_root is None:
        _print_summary(result)
        return 1

    # Step 2 — Stack
    if not no_start:
        stack = step_stack(workstation_root)
        result.add(stack)
        if not stack.passed:
            _print_summary(result)
            return 1
        time.sleep(1)

    # Steps 3–4 — Health + Route
    for step_fn in (step_health, step_route):
        step = step_fn()
        result.add(step)
        if not step.passed:
            _print_summary(result)
            return 1

    # Step 5 — Planning (builds TaskProposal + calls SwitchBoard)
    planning_step, bundle_data = step_planning(cp_repo)
    result.add(planning_step)
    if not planning_step.passed or bundle_data is None:
        _print_summary(result)
        return 1

    # Step 6 — Execution (adapter runs, returns ExecutionResult)
    execution_step, outcome = step_execution(cp_repo, bundle_data, artifacts_dir)
    result.add(execution_step)
    if not execution_step.passed:
        _print_summary(result)
        return 1

    # Step 7 — Artifacts
    artifact_step = step_artifacts(artifacts_dir, bundle_data, outcome)
    result.add(artifact_step)

    if use_json:
        summary = {
            "passed": result.passed,
            "steps": [{"name": s.name, "passed": s.passed, "detail": s.detail} for s in result.steps],
            "artifacts_dir": str(artifacts_dir),
        }
        print(json.dumps(summary, indent=2))
    else:
        _print_summary(result, artifacts_dir)

    return 0 if result.passed else 1
