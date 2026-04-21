"""fob demo — golden-path vertical-slice demo command.

Proves the full platform is operational:
  1. Preflight    — repos and config exist, required binaries available
  2. Stack        — WorkStation stack is healthy or started
  3. SwitchBoard  — sends a deterministic request, shows routing decision
  4. ControlPlane — sends a request as ControlPlane would (tenant headers),
                    proves the shared routing path works for autonomous traffic
  5. Summary      — per-step status, artifact locations, exit code
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── colour helpers ────────────────────────────────────────────────────────────

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


def _section(title: str) -> None:
    print()
    print(_c(f"── {title} ", "B", "CYN") + _c("─" * max(0, 48 - len(title)), "DIM"))


# ── result tracking ───────────────────────────────────────────────────────────

@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str = ""
    artifact: str = ""


@dataclass
class DemoResult:
    steps: list[StepResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def add(self, step: StepResult) -> None:
        self.steps.append(step)

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.steps)

    @property
    def failed_step(self) -> StepResult | None:
        return next((s for s in self.steps if not s.passed), None)


# ── HTTP helpers (no external deps beyond stdlib + optional httpx) ────────────

def _http_get(url: str, timeout: float = 5.0) -> tuple[int, Any]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except Exception:
        return 0, {}


def _http_post(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
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


# ── platform discovery ────────────────────────────────────────────────────────

def _find_workstation() -> Path | None:
    candidates = [
        Path(__file__).resolve().parents[4] / "WorkStation",
        Path.home() / "Documents" / "GitHub" / "WorkStation",
    ]
    for c in candidates:
        if (c / "scripts" / "ensure-up.sh").exists():
            return c
    return None


def _find_switchboard_url() -> str:
    port = os.environ.get("PORT_SWITCHBOARD", "20401")
    return f"http://localhost:{port}"


# ── demo steps ────────────────────────────────────────────────────────────────

def step_preflight(workstation_root: Path | None) -> StepResult:
    _section("1 · Preflight")

    issues: list[str] = []

    if workstation_root is None:
        issues.append("WorkStation repo not found (expected at ~/Documents/GitHub/WorkStation)")
    else:
        _ok(f"WorkStation : {workstation_root}")
        env_file = workstation_root / ".env"
        if not env_file.exists():
            issues.append(
                f".env missing in WorkStation — copy: cp .env.example .env"
            )
        else:
            _ok(".env present")

    for binary in ("docker",):
        result = subprocess.run(["which", binary], capture_output=True)
        if result.returncode == 0:
            _ok(f"{binary} available")
        else:
            issues.append(f"'{binary}' not found — install Docker")

    if issues:
        for issue in issues:
            _fail(issue)
        return StepResult("preflight", False, "; ".join(issues))
    return StepResult("preflight", True, "all checks passed")


def step_stack(workstation_root: Path) -> StepResult:
    _section("2 · Stack")

    script = workstation_root / "scripts" / "ensure-up.sh"
    if not script.exists():
        _fail(f"ensure-up.sh not found at {script}")
        return StepResult("stack", False, "ensure-up.sh missing")

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=False,
    )
    if result.returncode == 0:
        return StepResult("stack", True, "healthy")
    return StepResult("stack", False, f"ensure-up.sh exited {result.returncode}")


def step_health(switchboard_url: str) -> StepResult:
    _section("3 · Health")

    sb_port = switchboard_url.rsplit(":", 1)[-1]
    nr_port = os.environ.get("PORT_9ROUTER", "20128")

    all_ok = True
    for name, url in [
        ("SwitchBoard", f"http://localhost:{sb_port}/health"),
        ("9router    ", f"http://localhost:{nr_port}/health"),
    ]:
        code, body = _http_get(url, timeout=5)
        if code == 200:
            _ok(f"{name}  ({url})")
        else:
            _fail(f"{name}  ({url})  → HTTP {code or 'no response'}")
            all_ok = False

    return StepResult("health", all_ok, "all healthy" if all_ok else "one or more services unhealthy")


def step_switchboard_smoke(switchboard_url: str) -> StepResult:
    _section("4 · SwitchBoard routing proof")

    import uuid
    rid = uuid.uuid4().hex[:12]
    payload = {
        "model": "fast",
        "messages": [{"role": "user", "content": "Reply with a single word: ready"}],
    }
    headers = {
        "X-Request-ID": rid,
        "X-SwitchBoard-Tenant-ID": "fob-demo",
        "Authorization": "Bearer sk-demo",
    }

    _info(f"request_id : {rid}")
    _info(f"model hint : fast")

    code, body = _http_post(
        f"{switchboard_url}/v1/chat/completions",
        payload,
        headers=headers,
        timeout=30,
    )

    if code != 200:
        _fail(f"HTTP {code}  —  {json.dumps(body)[:120]}")
        return StepResult("switchboard", False, f"HTTP {code}")

    try:
        reply = body["choices"][0]["message"]["content"]
        _ok(f"response   : {reply!r}")
    except (KeyError, IndexError):
        _fail("unexpected response shape")
        return StepResult("switchboard", False, "malformed response")

    # Fetch the routing decision
    time.sleep(0.2)
    dcode, decisions = _http_get(
        f"{switchboard_url}/admin/decisions/recent?n=1", timeout=5
    )
    decision_detail = ""
    if dcode == 200 and decisions:
        d = decisions[0]
        profile = d.get("profile_name", "?")
        model   = d.get("downstream_model", "?")
        rule    = d.get("rule_name", "?")
        lat     = d.get("latency_ms")
        lat_str = f"{lat:.0f} ms" if lat is not None else "?"
        _ok(f"profile    : {profile}  →  {model}")
        _info(f"rule       : {rule}")
        _info(f"latency    : {lat_str}")
        decision_detail = f"profile={profile} model={model} rule={rule}"

    return StepResult("switchboard", True, decision_detail)


def step_controlplane_proof(switchboard_url: str) -> StepResult:
    _section("5 · ControlPlane routing proof")
    _info("Sending a request as ControlPlane would (X-SwitchBoard-Tenant-ID: control-plane)")

    import uuid
    rid = uuid.uuid4().hex[:12]
    payload = {
        "model": "capable",
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a planning assistant. "
                    "Reply with a single word: acknowledged"
                ),
            }
        ],
    }
    headers = {
        "X-Request-ID": rid,
        "X-SwitchBoard-Tenant-ID": "control-plane",
        "X-SwitchBoard-Profile": "capable",
        "Authorization": "Bearer sk-demo",
    }

    _info(f"request_id : {rid}")
    _info(f"profile    : capable (ControlPlane default)")

    code, body = _http_post(
        f"{switchboard_url}/v1/chat/completions",
        payload,
        headers=headers,
        timeout=30,
    )

    if code != 200:
        _fail(f"HTTP {code}  —  {json.dumps(body)[:120]}")
        return StepResult("controlplane", False, f"HTTP {code}")

    try:
        reply = body["choices"][0]["message"]["content"]
        _ok(f"response   : {reply!r}")
    except (KeyError, IndexError):
        _fail("unexpected response shape")
        return StepResult("controlplane", False, "malformed response")

    time.sleep(0.2)
    dcode, decisions = _http_get(
        f"{switchboard_url}/admin/decisions/recent?n=1", timeout=5
    )
    if dcode == 200 and decisions:
        d = decisions[0]
        tenant = d.get("tenant_id", "?")
        profile = d.get("profile_name", "?")
        _ok(f"tenant     : {tenant}  profile={profile}")

    return StepResult("controlplane", True, "ControlPlane traffic routed successfully")


# ── summary ───────────────────────────────────────────────────────────────────

def print_summary(result: DemoResult) -> None:
    elapsed = time.time() - result.started_at
    _section("Summary")
    for step in result.steps:
        icon = _c("✓", "GRN") if step.passed else _c("✗", "RED")
        detail = f"  {_c(step.detail, 'DIM')}" if step.detail else ""
        print(f"  {icon}  {step.name:<16}{detail}")
    print()
    print(f"  {_c('elapsed', 'DIM')} : {elapsed:.1f}s")
    print()
    if result.passed:
        print(_c("  DEMO PASSED — platform is operational.", "GRN", "B"))
    else:
        failed = result.failed_step
        if failed:
            print(_c(f"  DEMO FAILED at step: {failed.name}", "RED", "B"))
            if failed.detail:
                print(_c(f"  {failed.detail}", "DIM"))
        print()
        print(_c("  Logs / admin:", "DIM"))
        print(_c("    bash scripts/health.sh         (WorkStation)", "DIM"))
        print(_c("    curl localhost:20401/admin/decisions/recent?n=5", "DIM"))
    print()


# ── entry point ───────────────────────────────────────────────────────────────

def run_demo(args: list[str]) -> int:
    verbose    = "--verbose" in args or "-v" in args
    no_start   = "--no-start" in args
    as_json    = "--json" in args

    print(_c("\n  fob demo", "B", "CYN") + _c(" — platform vertical slice", "DIM"))

    workstation_root = _find_workstation()
    switchboard_url  = _find_switchboard_url()

    result = DemoResult()

    # 1. Preflight
    pre = step_preflight(workstation_root)
    result.add(pre)
    if not pre.passed:
        print_summary(result)
        return 1

    # 2. Stack
    if no_start:
        _section("2 · Stack")
        _info("--no-start: skipping stack launch")
        result.add(StepResult("stack", True, "skipped (--no-start)"))
    else:
        stack = step_stack(workstation_root)  # type: ignore[arg-type]
        result.add(stack)
        if not stack.passed:
            print_summary(result)
            return 1

    # 3. Health
    health = step_health(switchboard_url)
    result.add(health)
    if not health.passed:
        print_summary(result)
        return 1

    # 4. SwitchBoard smoke
    sb = step_switchboard_smoke(switchboard_url)
    result.add(sb)
    if not sb.passed:
        print_summary(result)
        return 1

    # 5. ControlPlane proof
    cp = step_controlplane_proof(switchboard_url)
    result.add(cp)

    if as_json:
        summary = {
            "passed": result.passed,
            "elapsed_s": round(time.time() - result.started_at, 1),
            "switchboard_url": switchboard_url,
            "steps": [
                {"name": s.name, "passed": s.passed, "detail": s.detail}
                for s in result.steps
            ],
        }
        print(json.dumps(summary, indent=2))
        return 0 if result.passed else 1

    print_summary(result)
    return 0 if result.passed else 1
