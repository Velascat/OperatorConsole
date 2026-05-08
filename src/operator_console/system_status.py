# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velascat
"""console status — show system readiness: SwitchBoard, OperationsCenter, lane binaries, last run."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

_C = {
    "R": "\033[0m", "B": "\033[1m", "DIM": "\033[2m",
    "RED": "\033[31m", "GRN": "\033[32m", "YLW": "\033[33m",
    "CYN": "\033[36m", "MAG": "\033[35m",
}


def _c(text: str, *keys: str) -> str:
    return "".join(_C[k] for k in keys) + text + _C["R"]


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _which(binary: str) -> bool:
    import subprocess
    try:
        return subprocess.run(["which", binary], capture_output=True, timeout=3).returncode == 0
    except Exception:
        return False


def _repo_root(name: str) -> Path:
    return Path.home() / "Documents" / "GitHub" / name


_WATCH_DIR = Path.home() / "Documents" / "GitHub" / "OperationsCenter" / "logs" / "local" / "watch-all"
_ROLES = ("intake", "goal", "test", "improve", "propose", "review", "spec", "watchdog")


def _watcher_status() -> dict[str, str]:
    """Return running/stopped status for each watcher role."""
    import subprocess
    statuses: dict[str, str] = {}
    for role in _ROLES:
        pid_file = _WATCH_DIR / f"{role}.pid"
        if pid_file.exists():
            try:
                pid = pid_file.read_text(encoding="utf-8").strip()
                alive = subprocess.run(
                    ["kill", "-0", pid], capture_output=True, timeout=3
                ).returncode == 0
                statuses[role] = "running" if alive else "stopped"
            except Exception:
                statuses[role] = "stopped"
        else:
            statuses[role] = "stopped"
    return statuses


def _row(label: str, ok: bool, detail: str = "") -> None:
    mark = _c("OK", "GRN") if ok else _c("--", "DIM")
    suffix = f"  {_c(detail, 'DIM')}" if detail else ""
    print(f"  {_c(label + ' ', 'DIM'):<26}{mark}{suffix}")


def _oc_budget() -> dict[str, Any]:
    """Read OC's execution usage + caps. Returns counts and limits.

    Path mirrors ``ExecutionControlSettings.usage_path`` default
    (``tools/report/operations_center/execution/usage.json``).
    Caps come from the same env vars OC reads at startup.

    Missing file or parse error → returns zero counts so the pane still
    renders something (the user is told the file is missing via ``found``).
    """
    repo = _repo_root("OperationsCenter")
    path = repo / "tools" / "report" / "operations_center" / "execution" / "usage.json"
    found = path.exists()
    hourly = daily = 0
    if found:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            hourly = int(data.get("hourly_exec_count", 0) or 0)
            daily = int(data.get("daily_exec_count", 0) or 0)
        except (OSError, ValueError, TypeError):
            found = False
    cap_hour = max(0, int(os.environ.get("OPERATIONS_CENTER_MAX_EXEC_PER_HOUR", "10")))
    cap_day = max(0, int(os.environ.get("OPERATIONS_CENTER_MAX_EXEC_PER_DAY", "50")))
    return {
        "found": found, "path": str(path),
        "hourly_used": hourly, "hourly_cap": cap_hour,
        "daily_used": daily, "daily_cap": cap_day,
    }


def _proc_count() -> int:
    """Count active processes via /proc.

    Works on Linux (including WSL2 Dave runs). Returns 0 if /proc isn't
    available so the rendering doesn't crash on macOS dev mode.
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return 0
    try:
        return sum(1 for entry in proc.iterdir() if entry.name.isdigit())
    except OSError:
        return 0


def _memory_summary() -> dict[str, Any]:
    """Read /proc/meminfo. Returns RAM and swap totals/used in MB.

    ``low_mem_threshold_mb`` is OC's kodo-side guardrail
    (``Settings.kodo.min_kodo_available_mb``, default 6144) — when free
    RAM drops below this OC blocks new kodo dispatches. Surfaced here
    so operators see *why* their budget might be silently throttled
    even when the cap looks unmet.

    Linux-only. Returns zeros when /proc/meminfo isn't readable.
    """
    info: dict[str, int] = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                value, _, unit = rest.strip().partition(" ")
                try:
                    kb = int(value)
                except ValueError:
                    continue
                if unit.lower().startswith("kb"):
                    info[key.strip()] = kb
    except OSError:
        pass

    def _mb(key: str) -> int:
        return info.get(key, 0) // 1024

    mem_total = _mb("MemTotal")
    mem_avail = _mb("MemAvailable")
    swap_total = _mb("SwapTotal")
    swap_free = _mb("SwapFree")
    mem_used = max(0, mem_total - mem_avail)
    swap_used = max(0, swap_total - swap_free)

    return {
        "mem_total_mb": mem_total,
        "mem_used_mb": mem_used,
        "mem_available_mb": mem_avail,
        "swap_total_mb": swap_total,
        "swap_used_mb": swap_used,
        "swap_free_mb": swap_free,
        # OC's kodo dispatch guardrail (config/operations_center.local.yaml::kodo.min_kodo_available_mb)
        "low_mem_threshold_mb": 6144,
    }


def run_status(args: list[str]) -> int:
    use_json = "--json" in args

    switchboard_port = os.environ.get("PORT_SWITCHBOARD", "20401")
    sb_health_url = f"http://localhost:{switchboard_port}/health"

    sb_ok = _http_ok(sb_health_url)
    cp_repo = _repo_root("OperationsCenter")
    cp_ok = (cp_repo / "src" / "operations_center" / "entrypoints" / "execute" / "main.py").exists()

    binaries = ["claude", "codex", "kodo", "aider"]
    binary_status = {b: _which(b) for b in binaries}
    watcher_statuses = _watcher_status()
    budget = _oc_budget()
    proc_count = _proc_count()
    mem = _memory_summary()

    from operator_console.runs import latest_run, run_summary
    last_run_dir = latest_run()
    last = run_summary(last_run_dir) if last_run_dir else None

    if use_json:
        payload = {
            "switchboard": {"ok": sb_ok, "url": sb_health_url},
            "operations_center": {"ok": cp_ok, "path": str(cp_repo)},
            "binaries": binary_status,
            "watchers": watcher_statuses,
            "execution_budget": budget,
            "system": {
                "process_count": proc_count,
                "memory": mem,
            },
            "last_run": last,
        }
        print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
        return 0

    print(_c("\n  console status", "B", "CYN") + _c(" — system readiness", "DIM"))
    print()

    # SwitchBoard
    _row("SwitchBoard", sb_ok, sb_health_url if sb_ok else f"not reachable at {sb_health_url}")

    # OperationsCenter
    _row("OperationsCenter", cp_ok, str(cp_repo) if cp_ok else f"not found at {cp_repo}")

    print()

    # Lane binaries
    print(_c("  Lanes", "B"))
    lane_map = {
        "claude": "claude_cli",
        "codex":  "codex_cli",
        "kodo":   "kodo",
        "aider":  "aider_local",
    }
    for binary, lane in lane_map.items():
        ok = binary_status[binary]
        mark = _c("available", "GRN") if ok else _c("unavailable", "DIM")
        print(f"    {_c(lane, 'DIM'):<22}{mark}  {_c(f'({binary})', 'DIM')}")

    print()

    # Watchers
    print(_c("  Watchers", "B"))
    for role, status in watcher_statuses.items():
        ok = status == "running"
        mark = _c("running", "GRN") if ok else _c("stopped", "DIM")
        print(f"    {_c(role, 'DIM'):<22}{mark}")

    print()

    # Execution budget — OC's hourly/daily caps + circuit-breaker context
    print(_c("  Execution budget", "B"))
    if budget["found"]:
        for win, used, cap in (
            ("hourly", budget["hourly_used"], budget["hourly_cap"]),
            ("daily ", budget["daily_used"],  budget["daily_cap"]),
        ):
            ratio = (used / cap) if cap else 0.0
            color = "RED" if ratio >= 1 else "YLW" if ratio >= 0.8 else "GRN"
            usage_disp = _c(f"{used}/{cap}", color)
            print(f"    {_c(win, 'DIM'):<22}{usage_disp}")
    else:
        print(f"    {_c('·', 'DIM')} usage.json not found ({budget['path']})")

    print()

    # System resources — process count + RAM/swap with kodo dispatch threshold
    print(_c("  System resources", "B"))
    print(f"    {_c('processes', 'DIM'):<22}{proc_count}")
    if mem["mem_total_mb"]:
        mem_low = mem["mem_available_mb"] < mem["low_mem_threshold_mb"]
        mem_color = "RED" if mem_low else "GRN"
        ram_disp = _c(
            f"{mem['mem_used_mb']}/{mem['mem_total_mb']} MB used  "
            f"({mem['mem_available_mb']} MB free, threshold {mem['low_mem_threshold_mb']} MB)",
            mem_color,
        )
        print(f"    {_c('ram', 'DIM'):<22}{ram_disp}")
    if mem["swap_total_mb"]:
        swap_ratio = mem["swap_used_mb"] / mem["swap_total_mb"]
        swap_color = "RED" if swap_ratio >= 0.8 else "YLW" if swap_ratio >= 0.5 else "GRN"
        swap_disp = _c(
            f"{mem['swap_used_mb']}/{mem['swap_total_mb']} MB used  "
            f"({mem['swap_free_mb']} MB free)",
            swap_color,
        )
        print(f"    {_c('swap', 'DIM'):<22}{swap_disp}")
    elif mem["mem_total_mb"]:
        print(f"    {_c('swap', 'DIM'):<22}{_c('disabled', 'DIM')}")

    print()

    # Last run
    if last:
        status = last.get("status", "unknown")
        success = last.get("success")
        run_id = last.get("run_id", "?")
        lane = last.get("selected_lane", "?")
        goal = last.get("goal_text") or "?"
        written_at = (last.get("written_at") or "?")[:19].replace("T", " ")

        status_color = "GRN" if success else "RED"
        status_disp = _c(status, status_color)
        goal_disp = goal[:50] + ("…" if len(goal) > 50 else "")

        print(_c("  Last run", "B"))
        print(f"    {_c('id     ', 'DIM')} {_c(run_id[:36], 'B')}")
        print(f"    {_c('status ', 'DIM')} {status_disp}")
        print(f"    {_c('lane   ', 'DIM')} {lane}")
        print(f"    {_c('goal   ', 'DIM')} {_c(goal_disp, 'DIM')}")
        print(f"    {_c('at     ', 'DIM')} {_c(written_at, 'DIM')}")
    else:
        print(_c("  Last run", "B"))
        print(f"    {_c('·', 'DIM')} no runs yet — try `console run` or `console demo`")

    print()

    overall_ok = sb_ok and cp_ok
    return 0 if overall_ok else 1
