# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velascat
"""Curses watcher-status pane — dense at-a-glance OperationsCenter monitor.

Sections (always visible):
  Roles       — running/stopped, pid, uptime, restart count (⚡)
  Campaigns   — active kodo campaigns from OC state
  Queue       — pending tasks filtered by --profile
  SwitchBoard — health check
  Resources   — load avg, RAM bar, swap bar

Arrows navigate roles. Enter opens action submenu:
  tail logs, board, circuit breaker, memory

Usage: python3 -m operator_console.watcher_status_pane [--profile <name>]
"""
from __future__ import annotations
import curses
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

_OC_ROOT    = Path.home() / "Documents" / "GitHub" / "OperationsCenter"
_WATCH_DIR  = _OC_ROOT / "logs" / "local" / "watch-all"
_STATE_DIR  = _OC_ROOT / "state"
_QUEUE_DIR  = Path.home() / ".console" / "queue"
_PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "profiles"

_ROLES   = ("intake", "goal", "test", "improve", "propose", "review", "spec", "watchdog")
_ACTIONS = ("tail logs", "board", "circuit breaker", "memory")

REFRESH_INTERVAL       = 3
PLANE_REFRESH_INTERVAL = 30
LOG_TAIL_LINES         = 60
BAR_W                  = 10   # width of █ progress bars

_OC_CONFIG = _OC_ROOT / "config" / "operations_center.local.yaml"

# States shown in each section
_BOARD_STATES  = {"ready for ai", "backlog"}
_ACTIVE_STATES = {"running"}


# ── Plane data collection ────────────────────────────────────────────────────

def _plane_config() -> dict | None:
    """Parse OC config for Plane connection details. Returns None if not configured.

    Avoids depending on PyYAML — the pane's Python may be a bare interpreter
    (e.g. pyenv system Python without site-packages). The `plane:` block is
    simple key-value pairs, so a manual parse is sufficient and robust.
    """
    if not _OC_CONFIG.exists():
        return None
    out = {
        "base_url":       "http://localhost:8080",
        "workspace_slug": "",
        "project_id":     "",
        "token_env":      "PLANE_API_TOKEN",
    }
    in_plane = False
    try:
        for raw in _OC_CONFIG.read_text(encoding="utf-8").splitlines():
            stripped = raw.rstrip()
            if not stripped or stripped.lstrip().startswith("#"):
                continue
            if not stripped.startswith(" ") and not stripped.startswith("\t"):
                in_plane = stripped.startswith("plane:")
                continue
            if not in_plane:
                continue
            line = stripped.strip()
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            v = v.strip().strip('"').strip("'")
            if not v:
                continue
            if k.strip() == "base_url":
                out["base_url"] = v.rstrip("/")
            elif k.strip() == "workspace_slug":
                out["workspace_slug"] = v
            elif k.strip() == "project_id":
                out["project_id"] = v
            elif k.strip() == "api_token_env":
                out["token_env"] = v
    except Exception:
        return None
    if not out["workspace_slug"] or not out["project_id"]:
        return None
    return out


def _read_token_from_env_file(token_env: str) -> str:
    """Read the Plane token from OperationsCenter's .env file.

    The status pane often outlives a token rotation; reading from the env file
    each fetch keeps it in sync without requiring a pane restart.
    """
    env_file = _OC_ROOT / ".env.operations-center.local"
    if not env_file.exists():
        return ""
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            k, _, v = line.partition("=")
            if k.strip() == token_env:
                return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _plane_get(cfg: dict, token: str, path: str) -> list[dict]:
    url = f"{cfg['base_url']}/api/v1/workspaces/{cfg['workspace_slug']}/projects/{cfg['project_id']}/{path}"
    req = urllib.request.Request(url, headers={"X-API-Key": token})
    try:
        with urllib.request.urlopen(req, timeout=4) as r:
            payload = json.loads(r.read())
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                return payload.get("results", [])
    except Exception:
        return []
    return []


def _plane_fetch(cfg: dict) -> list[dict]:
    """Fetch all work items from Plane with label IDs hydrated to names. [] on error."""
    token = _read_token_from_env_file(cfg["token_env"]) or os.environ.get(cfg["token_env"], "")
    if not token or not cfg["workspace_slug"] or not cfg["project_id"]:
        return []
    issues = _plane_get(cfg, token, "work-items/?expand=state")
    if not issues:
        return []
    # Plane returns label refs as UUIDs; resolve to names so _repo_from_labels works.
    labels = _plane_get(cfg, token, "labels/")
    by_id = {str(lab.get("id")): lab for lab in labels if isinstance(lab, dict) and lab.get("id")}
    for issue in issues:
        raw = issue.get("labels") or []
        if raw and not all(isinstance(r, dict) for r in raw):
            issue["labels"] = [by_id.get(str(r), {"name": ""}) if not isinstance(r, dict) else r for r in raw]
    return issues


def _repo_from_labels(labels: list) -> str:
    for lab in labels:
        name = (lab.get("name", "") if isinstance(lab, dict) else str(lab)).strip()
        if name.lower().startswith("repo:"):
            return name.split(":", 1)[1].strip()
    return ""


def _plane_issues(repo_filter: set[str] | None) -> dict[str, list[dict]]:
    """Return {"active": [...], "board": [...]} filtered by repo_filter."""
    cfg = _plane_config()
    if not cfg:
        return {"active": [], "board": []}
    issues = _plane_fetch(cfg)
    active, board = [], []
    for issue in issues:
        state_obj = issue.get("state")
        state_name = (state_obj.get("name", "") if isinstance(state_obj, dict) else str(state_obj or "")).strip()
        state_lower = state_name.lower()
        labels = issue.get("labels", [])
        repo = _repo_from_labels(labels)
        if repo_filter and repo not in repo_filter:
            continue
        item = {
            "title": issue.get("name", "Untitled"),
            "state": state_name,
            "repo":  repo or "?",
        }
        if state_lower in _ACTIVE_STATES:
            active.append(item)
        elif state_lower in _BOARD_STATES:
            board.append(item)
    return {"active": active, "board": board}


# ── data collection ───────────────────────────────────────────────────────────

def _pid_alive(pid: str) -> bool:
    try:
        return subprocess.run(["kill", "-0", pid], capture_output=True).returncode == 0
    except Exception:
        return False


_STALE_HEARTBEAT_S = 600  # 10 minutes — alert threshold

# Banner severity ordering: CRIT > WARN > INFO > HEALTHY. The cycle
# always renders all active conditions regardless of level; the
# severity tag drives the banner's color.
BANNER_CRIT = "critical"
BANNER_WARN = "warning"
BANNER_INFO = "info"
BANNER_HEALTHY = "healthy"
_BANNER_LEVEL_ORDER = (BANNER_CRIT, BANNER_WARN, BANNER_INFO, BANNER_HEALTHY)


def _banner_color(level: str, C: dict) -> int:
    """Pick the color attr for a banner of a given severity."""
    return {
        BANNER_CRIT:    C["BANNER_CRIT"],
        BANNER_WARN:    C["BANNER_WARN"],
        BANNER_INFO:    C["BANNER_INFO"],
        BANNER_HEALTHY: C["BANNER_HEALTHY"],
    }.get(level, C["BANNER_HEALTHY"]) | curses.A_BOLD


def _banner_conditions(data: dict, started_at: float) -> list[tuple[str, str]]:
    """Build the active banner list from a snapshot.

    Returns a list of ``(severity, message)`` tuples sorted worst-first.
    When nothing is wrong, returns a single HEALTHY entry so the always-on
    ribbon still renders.
    """
    conds: list[tuple[str, str]] = []

    # ── CRITICAL ──
    stale = _stale_heartbeat_roles()
    if stale:
        conds.append((
            BANNER_CRIT,
            f"⚠  STALL ALERT — {len(stale)} role(s) silent > "
            f"{_STALE_HEARTBEAT_S // 60}min: {', '.join(stale)}",
        ))
    if data.get("sb") is False:
        conds.append((
            BANNER_CRIT,
            "⚠  SwitchBoard Offline — Lane Selection Unavailable",
        ))
    # Resource gate at saturation = critical
    gate = data.get("resource_gate") or {}
    usage = data.get("backend_usage") or {}
    res = data.get("resources") or {}
    total_in_flight = sum(int(b.get("in_flight", 0)) for b in usage.values())
    mc = gate.get("max_concurrent")
    if mc is not None and total_in_flight >= mc:
        conds.append((
            BANNER_CRIT,
            f"⚠  Global Gate at Cap — {total_in_flight}/{mc} Dispatches "
            "in Flight; New Runs Blocked",
        ))
    floor_mb = gate.get("min_available_memory_mb")
    if floor_mb is not None:
        free_ram_mb = int(max(0, (res.get("mem_total_gb", 0)
                                  - res.get("mem_used_gb", 0))) * 1024)
        free_swap_mb = int(max(0, (res.get("swap_total_gb", 0)
                                   - res.get("swap_used_gb", 0))) * 1024)
        free_mb = free_ram_mb + free_swap_mb
        if free_mb and free_mb < floor_mb:
            conds.append((
                BANNER_CRIT,
                f"⚠  Memory Below Gate Floor — {free_mb}MB Free, "
                f"{floor_mb}MB Required",
            ))

    # ── WARNING ──
    caps = data.get("backend_caps") or {}
    saturated_backends: list[str] = []
    for backend, cap_cfg in caps.items():
        bu = usage.get(backend) or {}
        in_flight = int(bu.get("in_flight", 0))
        backend_mc = cap_cfg.get("max_concurrent")
        if backend_mc is not None and in_flight >= backend_mc:
            saturated_backends.append(f"{backend} {in_flight}/{backend_mc}")
    if saturated_backends:
        conds.append((
            BANNER_WARN,
            "⚠  Backend(s) at Concurrency Cap: "
            + ", ".join(saturated_backends),
        ))
    queue = data.get("queue") or []
    if len(queue) >= 10:
        conds.append((
            BANNER_WARN,
            f"⚠  Queue Depth {len(queue)} ≥ 10 — Backlog Accumulating",
        ))
    # Free RAM near the gate floor (within 1.2× of the floor)
    if floor_mb is not None:
        free_ram_mb = int(max(0, (res.get("mem_total_gb", 0)
                                  - res.get("mem_used_gb", 0))) * 1024)
        free_swap_mb = int(max(0, (res.get("swap_total_gb", 0)
                                   - res.get("swap_used_gb", 0))) * 1024)
        free_mb = free_ram_mb + free_swap_mb
        if free_mb and floor_mb <= free_mb < int(floor_mb * 1.2):
            conds.append((
                BANNER_WARN,
                f"⚠  Memory Near Gate Floor — {free_mb}MB Free vs "
                f"{floor_mb}MB Required (1.2× Margin)",
            ))

    # ── INFO ──
    # First 30 seconds after launch — readings may not be populated yet.
    if started_at and (time.time() - started_at) < 30:
        conds.append((
            BANNER_INFO,
            "ℹ  Just Started — Readings Stabilizing",
        ))

    if conds:
        # Sort by severity, preserving insertion order within each level.
        order = {lvl: i for i, lvl in enumerate(_BANNER_LEVEL_ORDER)}
        conds.sort(key=lambda c: order.get(c[0], 99))
        return conds

    return [(BANNER_HEALTHY, "✓  All Systems Nominal")]


def _stale_heartbeat_roles() -> list[str]:
    """Return role names that are not visibly healthy.

    A role is considered stalled when *any* of:
      - its supervisor PID file is missing or the PID is dead
        (the worker isn't running at all), OR
      - its heartbeat file is missing (no proof of life), OR
      - the heartbeat file is older than ``_STALE_HEARTBEAT_S``
        (process up but not ticking — hung).

    Iterating over the canonical ``_ROLES`` tuple guarantees every
    declared worker gets evaluated, including ones that never started
    (no heartbeat file would have been an invisible omission).
    """
    now = time.time()
    stale: list[str] = []
    for role in _ROLES:
        info = _role_info(role)
        if not info.get("alive", False):
            stale.append(role)
            continue
        hb = _WATCH_DIR / f"heartbeat_{role}.json"
        if not hb.exists():
            stale.append(role)
            continue
        try:
            age = now - hb.stat().st_mtime
        except OSError:
            stale.append(role)
            continue
        if age > _STALE_HEARTBEAT_S:
            stale.append(role)
    return sorted(stale)


def _role_info(role: str) -> dict:
    pid_file = _WATCH_DIR / f"{role}.pid"
    if not pid_file.exists():
        return {"alive": False, "pid": "", "mtime": None}
    try:
        pid = pid_file.read_text(encoding="utf-8").strip()
        alive = _pid_alive(pid)
        return {"alive": alive, "pid": pid, "mtime": pid_file.stat().st_mtime if alive else None}
    except Exception:
        return {"alive": False, "pid": "", "mtime": None}


def _restart_counts() -> dict[str, int]:
    """Count watcher_restart events per role from all log files."""
    counts: dict[str, int] = {}
    for log in _WATCH_DIR.glob("*.log"):
        try:
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                if "watcher_restart" not in line:
                    continue
                try:
                    ev = json.loads(line)
                    role = ev.get("role", "")
                    if role:
                        counts[role] = counts.get(role, 0) + 1
                except Exception:
                    pass
        except Exception:
            pass
    return counts


def _active_campaigns() -> list[dict]:
    f = _STATE_DIR / "campaigns" / "active.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("campaigns", [])
    except Exception:
        return []


def _sb_ok() -> bool:
    port = os.environ.get("PORT_SWITCHBOARD", "20401")
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _sys_resources() -> dict:
    load = "?"
    load_pct = "?"
    num_cores = 0
    try:
        parts = Path("/proc/loadavg").read_text(encoding="ascii").split()
        load = f"{parts[0]}/{parts[1]}/{parts[2]}"
        with open("/proc/cpuinfo", encoding="ascii") as f:
            num_cores = f.read().count("processor")
        if num_cores > 0:
            l1, l5, l15 = float(parts[0]), float(parts[1]), float(parts[2])
            p1, p5, p15 = int(100 * l1 / num_cores), int(100 * l5 / num_cores), int(100 * l15 / num_cores)
            load_pct = f"{p1}%/{p5}%/{p15}%"
    except Exception:
        pass

    mem_pct = swap_pct = 0
    mem_used_gb = mem_total_gb = swap_used_gb = swap_total_gb = 0.0
    try:
        info: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            k, *v = line.split()
            if v:
                info[k.rstrip(":")] = int(v[0])
        mt = info.get("MemTotal", 0)
        ma = info.get("MemAvailable", 0)
        st = info.get("SwapTotal", 0)
        sf = info.get("SwapFree", 0)
        if mt:
            mem_used_gb  = (mt - ma) / 1048576
            mem_total_gb = mt / 1048576
            mem_pct      = int(100 * (mt - ma) / mt)
        if st:
            swap_used_gb  = (st - sf) / 1048576
            swap_total_gb = st / 1048576
            swap_pct      = int(100 * (st - sf) / st)
    except Exception:
        pass

    return {
        "load": load,
        "load_pct": load_pct,
        "num_cores": num_cores,
        "mem_pct": mem_pct, "mem_used_gb": mem_used_gb, "mem_total_gb": mem_total_gb,
        "swap_pct": swap_pct, "swap_used_gb": swap_used_gb, "swap_total_gb": swap_total_gb,
    }


_USAGE_PATH = _OC_ROOT / "tools" / "report" / "operations_center" / "execution" / "usage.json"


def _exec_budget() -> dict:
    """Read OC's execution usage.json for global hourly/daily counts.

    Caps come from env (defaults match OC: 10/hour, 50/day). Missing or
    unreadable file returns zero counts so the pane keeps rendering.
    """
    hourly = daily = 0
    found = _USAGE_PATH.exists()
    if found:
        try:
            data = json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
            hourly = int(data.get("hourly_exec_count", 0) or 0)
            daily = int(data.get("daily_exec_count", 0) or 0)
        except Exception:
            found = False
    cap_hour = int(os.environ.get("OPERATIONS_CENTER_MAX_EXEC_PER_HOUR", "10"))
    cap_day = int(os.environ.get("OPERATIONS_CENTER_MAX_EXEC_PER_DAY", "50"))
    return {"found": found, "hourly_used": hourly, "hourly_cap": cap_hour,
            "daily_used": daily, "daily_cap": cap_day}


def _backend_caps() -> dict[str, dict[str, int]]:
    """Per-backend caps from OC's local YAML. Empty when unconfigured.

    Reuses the lightweight indented-block parser pattern this module
    already uses for the Plane block — keeps the pane bun-free even
    on a bare interpreter without PyYAML.
    """
    if not _OC_CONFIG.exists():
        return {}
    out: dict[str, dict[str, int]] = {}
    in_block = False
    current_backend: str | None = None
    try:
        for raw in _OC_CONFIG.read_text(encoding="utf-8").splitlines():
            stripped = raw.rstrip()
            if not stripped or stripped.lstrip().startswith("#"):
                continue
            if not stripped.startswith(" ") and not stripped.startswith("\t"):
                in_block = stripped.startswith("backend_caps:")
                current_backend = None
                continue
            if not in_block:
                continue
            # Determine indent level (2 spaces = backend, 4 spaces = field)
            indent = len(stripped) - len(stripped.lstrip())
            content = stripped.strip()
            if ":" not in content:
                continue
            key, _, val = content.partition(":")
            key = key.strip()
            # Strip trailing inline comment then quotes/whitespace.
            val = val.split("#", 1)[0].strip().strip('"').strip("'")
            if indent == 2:
                # New backend section starts
                current_backend = key
                out.setdefault(current_backend, {})
            elif indent == 4 and current_backend is not None and val:
                if key in ("max_per_hour", "max_per_day",
                           "min_available_memory_mb", "max_concurrent"):
                    try:
                        out[current_backend][key] = int(val)
                    except ValueError:
                        pass
    except Exception:
        return {}
    # Drop empty stub entries (a backend with no fields)
    return {k: v for k, v in out.items() if v}


def _resource_gate() -> dict[str, int]:
    """Read OC's global ``resource_gate:`` block from local YAML.

    Returns ``{"max_concurrent": int, "min_available_memory_mb": int}``
    with absent fields omitted. Empty dict when the block is missing
    or unparseable. Mirrors the lightweight indented-block parser used
    by ``_backend_caps`` so the pane stays bun-free.
    """
    if not _OC_CONFIG.exists():
        return {}
    out: dict[str, int] = {}
    in_block = False
    try:
        for raw in _OC_CONFIG.read_text(encoding="utf-8").splitlines():
            stripped = raw.rstrip()
            if not stripped or stripped.lstrip().startswith("#"):
                continue
            # Top-level boundary: starts at column 0.
            if not stripped.startswith(" ") and not stripped.startswith("\t"):
                in_block = stripped.startswith("resource_gate:")
                continue
            if not in_block:
                continue
            content = stripped.strip()
            if ":" not in content:
                continue
            key, _, val = content.partition(":")
            key = key.strip()
            val = val.split("#", 1)[0].strip().strip('"').strip("'")
            if key in ("max_concurrent", "min_available_memory_mb") and val:
                try:
                    out[key] = int(val)
                except ValueError:
                    pass
    except Exception:
        return {}
    return out


def _backend_usage() -> dict[str, dict[str, int]]:
    """Per-backend live counters from usage.json events.

    Returns ``{backend: {"hourly": int, "daily": int, "in_flight": int}}``
    with the same logic as ``UsageStore.budget_decision_for_backend`` and
    ``concurrent_runs_for_backend``. Missing/unreadable file → ``{}``.
    """
    if not _USAGE_PATH.exists():
        return {}
    try:
        data = json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    events = data.get("events", []) or []
    now = time.time()
    cutoff_hour = now - 3600
    cutoff_day = now - 86400
    cutoff_concurrency = now - 86400  # 24h stale window
    per: dict[str, dict] = {}
    in_flight: dict[str, set[str]] = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        backend = ev.get("backend")
        if not isinstance(backend, str) or not backend:
            continue
        ts_raw = ev.get("timestamp")
        if not isinstance(ts_raw, str):
            continue
        try:
            # Strip timezone and parse ISO; fall back gracefully.
            from datetime import datetime as _dt
            ts = _dt.fromisoformat(ts_raw).timestamp()
        except (ValueError, OverflowError):
            continue
        bucket = per.setdefault(backend, {"hourly": 0, "daily": 0})
        kind = ev.get("kind")
        if kind == "execution":
            if ts >= cutoff_day:
                bucket["daily"] += 1
                if ts >= cutoff_hour:
                    bucket["hourly"] += 1
        elif ts >= cutoff_concurrency:
            tid = ev.get("task_id")
            if isinstance(tid, str):
                if kind == "execution_started":
                    in_flight.setdefault(backend, set()).add(tid)
                elif kind == "execution_finished":
                    in_flight.setdefault(backend, set()).discard(tid)
    for backend, ids in in_flight.items():
        per.setdefault(backend, {"hourly": 0, "daily": 0})["in_flight"] = len(ids)
    for bucket in per.values():
        bucket.setdefault("in_flight", 0)
    return {k: dict(v) for k, v in per.items()}


def _profile_repos(profile_name: str) -> set[str] | None:
    try:
        from operator_console.profile_loader import load_profile
        p = load_profile(profile_name, _PROFILES_DIR)
        if "group" in p:
            names: set[str] = set()
            for sub in p["group"]:
                try:
                    sp = load_profile(sub, _PROFILES_DIR)
                    names.add(sp.get("name", sub))
                except Exception:
                    names.add(sub)
            return names
        return {p["name"]} if "name" in p else None
    except Exception:
        return None


def _queue_items(repo_filter: set[str] | None) -> list[dict]:
    items = []
    if not _QUEUE_DIR.exists():
        return items
    for f in sorted(_QUEUE_DIR.glob("*.json")):
        try:
            item = json.loads(f.read_text(encoding="utf-8"))
            if repo_filter is None or item.get("repo_name") in repo_filter:
                items.append(item)
        except Exception:
            pass
    return items


_plane_cache: dict = {"active": [], "board": [], "fetched_at": 0.0}


def _collect(repo_filter: set[str] | None) -> dict:
    global _plane_cache
    now = time.time()
    if now - _plane_cache["fetched_at"] >= PLANE_REFRESH_INTERVAL:
        fresh = _plane_issues(repo_filter)
        _plane_cache = {**fresh, "fetched_at": now}
    return {
        "roles":     {r: _role_info(r) for r in _ROLES},
        "restarts":  _restart_counts(),
        "campaigns": _active_campaigns(),
        "sb":        _sb_ok(),
        "queue":     _queue_items(repo_filter),
        "resources": _sys_resources(),
        "plane":     {"active": _plane_cache["active"], "board": _plane_cache["board"]},
        "recent":    _recent_activity(),
        "budget":    _exec_budget(),
        "backend_caps":  _backend_caps(),
        "backend_usage": _backend_usage(),
        "resource_gate": _resource_gate(),
        "at":        now,
    }


# ── drawing helpers ───────────────────────────────────────────────────────────

def _put(stdscr, row: int, h: int, w: int, text: str, attr: int = 0) -> None:
    if row < 0 or row >= h:
        return
    try:
        stdscr.addstr(row, 0, text[: w - 1].ljust(min(len(text) + 1, w - 1)), attr)
    except curses.error:
        pass


def _sep(stdscr, row: int, h: int, w: int, attr: int) -> int:
    _put(stdscr, row, h, w, "─" * (w - 1), attr)
    return row + 1


def _bar(pct: int, width: int = BAR_W) -> str:
    filled = round(pct * width / 100)
    return "█" * filled + "░" * (width - filled)


def _uptime(start: float) -> str:
    e = int(time.time() - start)
    if e < 60:
        return f"{e}s"
    if e < 3600:
        return f"{e // 60}m"
    return f"{e // 3600}h{(e % 3600) // 60}m"


def _latest_log(role: str) -> Path | None:
    logs = sorted(_WATCH_DIR.glob(f"*_{role}.log"))
    return logs[-1] if logs else None


_RECENT_WINDOW_S = 300  # 5 minutes
_RECENT_PAT = re.compile(
    r"^(\d{2}:\d{2}:\d{2}) \[(\w+)\] (?:INFO|WARNING) board_worker\[\w+\]: "
    r"(?:task_id=\S+\s+)?"
    r"(claimed|completed|blocked|processing|failed)"
    r"(?:.*?status=(\S+))?"
    r"(?:.*?title=[\"\']([^\"\']{0,60}))?"
)


def _recent_activity() -> list[dict]:
    """Mine worker logs for claim/complete/block events in the last _RECENT_WINDOW_S seconds.

    Returns events newest-first as {role, action, status, title, ts} dicts.
    """
    cutoff = time.time() - _RECENT_WINDOW_S
    events: list[dict] = []
    for role in ("goal", "test", "improve"):
        log = _latest_log(role)
        if not log:
            continue
        try:
            mtime = log.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Walk lines newest-first; stop after a few hits per role
        lines = text.splitlines()
        per_role = 0
        for raw in reversed(lines):
            if "board_worker[" not in raw:
                continue
            if not any(k in raw for k in (" claimed ", " completed ", " blocked ", " processing ", " failed ")):
                continue
            m = _RECENT_PAT.match(raw)
            if not m:
                continue
            ts_str, lrole, action, status, title = m.groups()
            events.append({
                "role":   lrole,
                "action": action,
                "status": status or "",
                "title":  (title or "").strip("`* "),
                "ts":     ts_str,
            })
            per_role += 1
            if per_role >= 5:
                break
    return events


# ── main view ─────────────────────────────────────────────────────────────────

_SEP_MARKER = "\x00SEP\x00"   # synthetic line that renders as a separator


def _build_sections(
    data: dict, sel: int, w: int, C: dict,
) -> tuple[list[dict], int]:
    """Build the middle area as a list of independently scrollable sections.

    Each section is a dict::

        {"id": str, "lines": [(text, attr), ...], "sel_local": int}

    ``sel_local`` is the line index *within the section* of the currently
    selected role (only set for the "roles" section; -1 elsewhere). The
    caller uses it to keep the selection visible when scrolling the
    roles section.

    Returns ``(sections, focused_section_idx)`` — focused section is
    where the selected role lives (always 0 today since "roles" is
    always first), used as the default target for keyboard scroll keys.
    """
    sections: list[dict] = []

    # ── roles section ──
    role_lines: list[tuple[str, int]] = []
    role_sel_local = -1
    roles    = data.get("roles", {})
    restarts = data.get("restarts", {})
    n_up = sum(1 for r in _ROLES if roles.get(r, {}).get("alive", False))
    total_rc = sum(restarts.get(r, 0) for r in _ROLES)
    hdr_attr = (C["YLW"] | curses.A_BOLD) if (n_up < len(_ROLES) or total_rc > 0) else (C["HEAD"] | curses.A_BOLD)
    rc_tag = f"{total_rc} Restarts" if total_rc else "Clean"
    role_lines.append((f" Workers ({n_up}/{len(_ROLES)} Running, {rc_tag})", hdr_attr))
    for i, role in enumerate(_ROLES):
        info  = roles.get(role, {})
        alive = info.get("alive", False)
        rc    = restarts.get(role, 0)
        rb    = f" ↺{rc}" if rc else ""
        if alive:
            up   = _uptime(info["mtime"]) if info.get("mtime") else "?"
            line = f"  ✓  {role:<11} up {up}{rb}"
            attr = C["RUN"]
        else:
            line = f"  ✗  {role:<11} STOPPED{rb}"
            attr = C["ERR"]
        if i == sel:
            role_sel_local = len(role_lines)
            full = ("▶" + line[1:] + " [Enter]")[:w - 1]
            role_lines.append((full, C["SEL"] | curses.A_BOLD))
        else:
            role_lines.append((line, attr))
    sections.append({"id": "roles", "lines": role_lines, "sel_local": role_sel_local})

    # ── active tasks (Plane: Running) ──
    plane = data.get("plane", {})
    active_tasks = plane.get("active", [])
    if active_tasks:
        active_lines: list[tuple[str, int]] = [
            (f" Active ({len(active_tasks)} Running)", C["HEAD"] | curses.A_BOLD),
        ]
        for item in active_tasks:
            repo  = item.get("repo", "?")[:10]
            title = item.get("title", "?")[:max(w - 16, 8)]
            active_lines.append((f"  ▶  {repo:<11} {title}", C["RUN"]))
        sections.append({"id": "active", "lines": active_lines, "sel_local": -1})

    # ── recent activity (worker logs) ──
    recent = data.get("recent", [])
    if recent:
        recent_lines: list[tuple[str, int]] = [
            (f" Recent ({len(recent)} Events, Last 5m)", C["HEAD"] | curses.A_BOLD),
        ]
        for ev in recent[:8]:
            action = ev.get("action", "")
            status = ev.get("status", "")
            title  = ev.get("title", "")[:max(w - 32, 8)]
            role   = ev.get("role", "")
            ts     = ev.get("ts", "")
            if action == "blocked":
                icon, attr = "✗", C["ERR"]
            elif action == "completed":
                icon, attr = "✓", C["RUN"]
            elif action == "claimed":
                icon, attr = "→", C["YLW"]
            else:
                icon, attr = "·", C["DIM"]
            tag = f"{action}({status})" if status else action
            recent_lines.append((f"  {icon}  {ts} {role:<8} {tag:<22} {title}", attr))
        sections.append({"id": "recent", "lines": recent_lines, "sel_local": -1})

    # ── board ──
    board_items = plane.get("board", [])
    if board_items:
        board_lines: list[tuple[str, int]] = [
            (f" Board ({len(board_items)} Queued)", C["HEAD"] | curses.A_BOLD),
        ]
        for item in board_items:
            repo  = item.get("repo", "?")[:10]
            state = item.get("state", "")
            icon  = "·" if "backlog" in state.lower() else "→"
            title = item.get("title", "?")[:max(w - 16, 8)]
            board_lines.append((f"  {icon}  {repo:<11} {title}", C["DIM"]))
        sections.append({"id": "board", "lines": board_lines, "sel_local": -1})

    # ── campaigns ──
    campaigns = data.get("campaigns", [])
    if campaigns:
        camp_lines: list[tuple[str, int]] = [
            (f" Campaigns ({len(campaigns)} Active)", C["HEAD"] | curses.A_BOLD),
        ]
        for c in campaigns:
            slug   = c.get("slug", c.get("campaign_id", "?"))[:w - 6]
            status = c.get("status", "")
            if status == "done":
                icon, attr = "✓", C["RUN"]
            elif status == "failed":
                icon, attr = "✗", C["ERR"]
            else:
                icon, attr = "▶", C["YLW"]
            camp_lines.append((f"  {icon}  {slug}", attr))
        sections.append({"id": "campaigns", "lines": camp_lines, "sel_local": -1})

    # ── queue ──
    queue = data.get("queue", [])
    if queue:
        # Backlog signal: 0 → green, 1-4 → green, 5-9 → yellow, ≥10 → red.
        n_q = len(queue)
        q_attr = (
            C["ERR"] if n_q >= 10
            else C["YLW"] if n_q >= 5
            else C["RUN"] if n_q else C["HEAD"]
        )
        queue_lines: list[tuple[str, int]] = [
            (f" Queue ({n_q} Pending)", q_attr | curses.A_BOLD),
        ]
        for item in queue:
            typ  = (item.get("task_type") or "?")[:4]
            repo = (item.get("repo_name") or "?")[:10]
            goal = (item.get("goal") or "")[:max(w - 20, 8)]
            queue_lines.append((f"  {typ:<5} {repo:<11} {goal}", C["DIM"]))
        sections.append({"id": "queue", "lines": queue_lines, "sel_local": -1})

    # ── execution budget (global hourly/daily caps) ──
    budget = data.get("budget", {})
    if budget.get("found"):
        # Compute the worst color across both windows so the section
        # header reflects the budget's overall state.
        budget_worst = C["RUN"]
        rows: list[tuple[str, int]] = []
        for win, used, cap in (
            ("Hourly", budget.get("hourly_used", 0), budget.get("hourly_cap", 0)),
            ("Daily ", budget.get("daily_used", 0),  budget.get("daily_cap", 0)),
        ):
            ratio = (used / cap) if cap else 0.0
            attr = (
                C["ERR"] if ratio >= 1
                else C["YLW"] if ratio >= 0.8
                else C["RUN"]
            )
            if attr is C["ERR"]:
                budget_worst = C["ERR"]
            elif attr is C["YLW"] and budget_worst is C["RUN"]:
                budget_worst = C["YLW"]
            rows.append((f"  {win}  {used}/{cap}", attr))
        budget_lines: list[tuple[str, int]] = [
            (" Execution Budget", budget_worst | curses.A_BOLD),
            *rows,
        ]
        sections.append({"id": "budget", "lines": budget_lines, "sel_local": -1})

    # ── backend caps (per-backend rate / concurrency / RAM) ──
    caps = data.get("backend_caps", {})
    usage = data.get("backend_usage", {})
    res = data.get("resources", {})
    mem_avail_mb = 0
    if res.get("mem_total_gb"):
        mem_avail_mb = int(
            (res["mem_total_gb"] - res.get("mem_used_gb", 0)) * 1024
        )
    if caps or usage:
        bc_lines: list[tuple[str, int]] = []
        bc_section_worst = C["RUN"]
        for backend in sorted(set(caps) | set(usage)):
            bc = caps.get(backend, {})
            bu = usage.get(backend, {})
            cells: list[str] = []
            worst_attr = C["RUN"]
            for win_label, used_key, cap_key in (
                ("h", "hourly", "max_per_hour"),
                ("d", "daily",  "max_per_day"),
            ):
                limit = bc.get(cap_key)
                used = bu.get(used_key, 0)
                if limit is not None:
                    ratio = (used / limit) if limit else 0.0
                    if ratio >= 1:
                        worst_attr = C["ERR"]
                    elif ratio >= 0.8 and worst_attr is C["RUN"]:
                        worst_attr = C["YLW"]
                    cells.append(f"{win_label}={used}/{limit}")
                elif used:
                    cells.append(f"{win_label}={used}/∞")
            in_flight = bu.get("in_flight", 0)
            mc = bc.get("max_concurrent")
            if mc is not None:
                ratio = (in_flight / mc) if mc else 0.0
                if ratio >= 1:
                    worst_attr = C["ERR"]
                elif ratio >= 0.8 and worst_attr is C["RUN"]:
                    worst_attr = C["YLW"]
                cells.append(f"in_flight={in_flight}/{mc}")
            elif in_flight:
                cells.append(f"in_flight={in_flight}/∞")
            ram_floor = bc.get("min_available_memory_mb")
            if ram_floor is not None:
                if mem_avail_mb and mem_avail_mb < ram_floor:
                    worst_attr = C["ERR"]
                cells.append(f"ram≥{ram_floor}MB")
            row = "  ".join(cells) if cells else "(No Caps)"
            bc_lines.append((f"  {backend:<10} {row}", worst_attr))
            if worst_attr is C["ERR"]:
                bc_section_worst = C["ERR"]
            elif worst_attr is C["YLW"] and bc_section_worst is C["RUN"]:
                bc_section_worst = C["YLW"]
        sections.append({"id": "backend_caps", "lines": [
            (" Backend Caps", bc_section_worst | curses.A_BOLD),
            *bc_lines,
        ], "sel_local": -1})

    # ── services ──
    sb = data.get("sb", False)
    sb_icon = "✓" if sb else "✗"
    sb_attr = C["RUN"] if sb else C["ERR"]
    sections.append({"id": "services", "lines": [
        (" Services", sb_attr | curses.A_BOLD),
        (f"  {sb_icon} SwitchBoard", sb_attr),
    ], "sel_local": -1})

    # Focused section = the one containing the selected role (always 0 today
    # since "roles" is always the first section). Keyboard PgUp/PgDn target this.
    focused_idx = 0
    return sections, focused_idx


def _resources_lines(data: dict, C: dict) -> list[tuple[str, int]]:
    """Build the System Resources block as lines. Always anchored to bottom."""
    out: list[tuple[str, int]] = []
    res = data.get("resources", {})
    out.append((_SEP_MARKER, C["DIM"]))
    # Blank spacer above the section title so the block visually
    # detaches from whatever rendered above it.
    out.append(("", 0))
    out.append((" System Resources", C["HEAD"] | curses.A_BOLD))
    out.append((f"  {'':15}  {'1m':>7} {'5m':>7} {'15m':>7}", C["DIM"]))

    load_str = res.get('load', '?')
    parts = load_str.split('/') if '/' in load_str else ['?', '?', '?']
    out.append((f"  {'Processes/Queue':15}  {parts[0]:>7} {parts[1]:>7} {parts[2]:>7}", C["DIM"]))

    load_pct_str = res.get('load_pct', '?')
    num_cores = res.get('num_cores', 0)
    cores_str = f"({num_cores} cores)" if num_cores > 0 else ""
    pct_parts = load_pct_str.split('/') if '/' in load_pct_str else ['?', '?', '?']
    out.append((f"  {'CPU Utilization':15}  {pct_parts[0]:>7} {pct_parts[1]:>7} {pct_parts[2]:>7}  {cores_str}", C["DIM"]))

    mp  = res.get("mem_pct", 0)
    mug = res.get("mem_used_gb", 0)
    mtg = res.get("mem_total_gb", 0)
    out.append((f"  {'RAM':15}  {_bar(mp):>7} {mp:>3d}%  {mug:.1f}/{mtg:.1f}G",
                C["YLW"] if mp > 80 else C["DIM"]))

    if res.get("swap_total_gb", 0) > 0:
        sp  = res.get("swap_pct", 0)
        sug = res.get("swap_used_gb", 0)
        stg = res.get("swap_total_gb", 0)
        out.append((f"  {'Swap':15}  {_bar(sp):>7} {sp:>3d}%  {sug:.1f}/{stg:.1f}G",
                    C["YLW"] if sp > 50 else C["DIM"]))

    # ── Global resource gate (OC's resource_gate: block) ──
    # Always render the row so operators can see whether the gate is
    # configured at all. When unset, show "(unset)" so it's obvious
    # the feature exists but no floor is enforced.
    gate = data.get("resource_gate", {}) or {}
    usage = data.get("backend_usage", {}) or {}
    total_in_flight = sum(int(b.get("in_flight", 0)) for b in usage.values())
    # Available memory = free RAM + free swap. Matches OC's
    # UsageStore.available_memory_mb() so the watcher and the
    # actual gate enforcement compare against the same number.
    mem_total_gb = res.get("mem_total_gb", 0)
    mem_used_gb = res.get("mem_used_gb", 0)
    swap_total_gb = res.get("swap_total_gb", 0)
    swap_used_gb = res.get("swap_used_gb", 0)
    free_ram_mb = int(max(0, (mem_total_gb - mem_used_gb)) * 1024) if mem_total_gb else 0
    free_swap_mb = int(max(0, (swap_total_gb - swap_used_gb)) * 1024) if swap_total_gb else 0
    free_mb = free_ram_mb + free_swap_mb

    mc = gate.get("max_concurrent")
    floor_mb = gate.get("min_available_memory_mb")

    if mc is None and floor_mb is None:
        out.append((f"  {'Global Gate':15}  (Unset)", C["DIM"]))
    else:
        # Concurrency cell
        if mc is not None:
            ratio = (total_in_flight / mc) if mc else 0.0
            conc_attr = (
                C["ERR"] if ratio >= 1.0
                else C["YLW"] if ratio >= 0.8
                else C["RUN"]
            )
            conc_cell = f"i-f {total_in_flight}/{mc}"
        else:
            conc_attr = C["DIM"]
            conc_cell = f"i-f {total_in_flight}/∞"
        # Memory-floor cell. "free" sums RAM + swap, matching OC's
        # gate enforcement (UsageStore.available_memory_mb()).
        if floor_mb is not None:
            ram_attr = C["ERR"] if free_mb and free_mb < floor_mb else C["RUN"]
            ram_cell = f"mem≥{floor_mb}MB ({free_mb} free)"
        else:
            ram_attr = C["DIM"]
            ram_cell = "mem≥∞"
        # Worst color wins for the line
        worst = ram_attr if ram_attr is C["ERR"] else (
            conc_attr if conc_attr is C["ERR"] else
            ram_attr if ram_attr is C["YLW"] else
            conc_attr if conc_attr is C["YLW"] else
            C["DIM"]
        )
        out.append((f"  {'Global Gate':15}  {conc_cell}  {ram_cell}", worst))
    # Blank spacer at the bottom so the block visually separates from
    # whatever sits below it (typically the footer).
    out.append(("", 0))
    return out


_SIZE_MULT_MIN = 0.3
_SIZE_MULT_MAX = 3.0
_SIZE_MULT_STEP = 0.25


def _allocate_section_rows(
    sections: list[dict],
    available_rows: int,
    *,
    collapsed: dict[str, bool] | None = None,
    size_mult: dict[str, float] | None = None,
) -> list[int]:
    """Decide how many on-screen rows each section gets.

    Each section requests an effective natural height = ``len(lines) *
    size_mult.get(id, 1.0)``, rounded. Collapsed sections request 1
    (header only). If the total fits, every section gets its full ask.
    Otherwise, give each section its proportional share with a minimum
    of 3 rows so even tiny sections keep their header visible.
    Collapsed sections always render exactly 1 row and don't compete.
    """
    collapsed = collapsed or {}
    size_mult = size_mult or {}
    if available_rows <= 0 or not sections:
        return [0] * len(sections)
    # Effective natural per section: collapsed → 1, else ceil(lines * mult).
    natural: list[int] = []
    for s in sections:
        if not s["lines"]:
            natural.append(0)
            continue
        if collapsed.get(s["id"], False):
            natural.append(1)
            continue
        mult = size_mult.get(s["id"], 1.0)
        # Round up so a 0.5x section still gets at least 1 line beyond its header.
        from math import ceil
        natural.append(max(1, ceil(len(s["lines"]) * mult)))
    total = sum(natural)
    if total <= available_rows:
        return natural[:]
    # Overflow — proportionally allocate, min 3 rows for non-empty sections.
    # Collapsed sections keep their 1-row reservation regardless.
    is_collapsed = [collapsed.get(s["id"], False) for s in sections]
    fixed = [
        1 if is_collapsed[i] and natural[i] > 0
        else (min(3, available_rows // max(1, sum(1 for n in natural if n > 0))) if natural[i] > 0 else 0)
        for i in range(len(sections))
    ]
    fixed_sum = sum(fixed)
    leftover = max(0, available_rows - fixed_sum)
    # Only non-collapsed sections compete for extra rows.
    extra_demand = sum(
        max(0, natural[i] - fixed[i])
        for i in range(len(sections))
        if not is_collapsed[i]
    )
    out = list(fixed)
    if extra_demand > 0:
        for i, n in enumerate(natural):
            if not is_collapsed[i] and n > fixed[i]:
                share = (n - fixed[i]) * leftover // extra_demand
                out[i] += share
    out = [min(o, n) for o, n in zip(out, natural, strict=False)]
    return out


_HINT_CHUNKS: tuple[str, ...] = (
    "↑↓ Role",
    "Wheel Scroll",
    "Click Header Collapse",
    "+/- Resize",
    "= Reset",
    "Enter Actions",
    "c Collapse",
    "r Refresh",
    "? Hints",
    "q Quit",
)


def _wrap_hints(chunks: tuple[str, ...], width: int) -> list[str]:
    """Greedily wrap chunks into lines fitting width, two-space separator."""
    if width <= 0:
        return [""]
    lines: list[str] = []
    cur = ""
    for chunk in chunks:
        candidate = chunk if not cur else f"{cur}  {chunk}"
        if len(candidate) <= width:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = chunk if len(chunk) <= width else chunk[:width]
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw_main(
    stdscr, data: dict, sel: int, refreshing: bool, flash: str, C: dict,
    section_offsets: dict[str, int],
    *,
    collapsed: dict[str, bool] | None = None,
    size_mult: dict[str, float] | None = None,
    focused_section: str | None = None,
    banner_offset: int = 0,
    current_banner: tuple[str, str] = (BANNER_HEALTHY, "✓  All Systems Nominal"),
    banner_count: int = 1,
    banner_index: int = 0,
    hints_collapsed: bool = True,
) -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
    """Render the main view with per-section scroll/collapse/size state.

    Each top-level section (roles / active / recent / board / campaigns /
    queue / budget / backend_caps / services) renders inside its own row
    range with its own scroll offset (mutated in-place on
    ``section_offsets``). Mouse-wheel events route to whichever section
    the cursor is over; click-on-header toggles the section's collapsed
    state; ``+``/``-`` keys grow/shrink the focused section's allocation.

    Returns ``(section_rows, header_rows)``:
      - ``section_rows[sid] = (start, end_exclusive)`` for hit-testing
        wheel scrolls anywhere in the section
      - ``header_rows[sid] = row`` of the section's header line for
        hit-testing collapse-toggle clicks
    """
    collapsed = collapsed or {}
    size_mult = size_mult or {}
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    def put(r, t, a=0):
        return _put(stdscr, r, h, w, t, a)

    spin = " ⟳" if refreshing else "  "
    ts   = time.strftime("%H:%M:%S")

    # Always-on banner block. HEALTHY when no warnings; cycles through
    # all active conditions worst-first. Layout (rows 0-6):
    #   divider (0) → marquee (1) → divider (2) → blank (3) →
    #   title (4) → blank (5) → divider (6) → first section (7).
    severity, message = current_banner
    counter = (
        f"  [{banner_index + 1}/{banner_count}]" if banner_count > 1 else ""
    )
    banner_payload = f" {message}{counter} "
    gap = "    "
    loop = banner_payload + gap
    # Repeat until at least 2× window width so any offset slice
    # contains a full banner copy without wrap glue.
    while len(loop) < (w - 1) * 2:
        loop += banner_payload + gap
    offset = (banner_offset or 0) % (len(banner_payload) + len(gap))
    view = loop[offset:offset + (w - 1)]
    _sep(stdscr, 0, h, w, C["DIM"])
    put(1, view, _banner_color(severity, C))
    _sep(stdscr, 2, h, w, C["DIM"])
    put(3, "", 0)
    put(4, f" Operations Center{spin}  {ts}", C["HEAD"] | curses.A_BOLD)
    put(5, "", 0)
    _sep(stdscr, 6, h, w, C["DIM"])

    sections, focused_idx = _build_sections(data, sel, w, C)
    bottom_lines = _resources_lines(data, C)

    # Decorate section headers with a collapse indicator + focus highlight.
    # Modifies sections in place — they're freshly built each frame.
    for sec in sections:
        if not sec["lines"]:
            continue
        text, attr = sec["lines"][0]
        is_collapsed = collapsed.get(sec["id"], False)
        marker = "▶ " if is_collapsed else "▼ "
        # Strip the original leading space so the marker takes its place.
        new_text = marker + text.lstrip()
        if focused_section == sec["id"]:
            new_text += "  ← Focused"
        # Show non-default size multiplier so operators can see what they did.
        mult = size_mult.get(sec["id"], 1.0)
        if abs(mult - 1.0) > 0.01:
            new_text += f"  [{mult:.2f}×]"
        sec["lines"][0] = (new_text, attr)

    bottom_h   = len(bottom_lines)
    # Footer block (bottom-up): divider → hint area → divider.
    # Hint area is one row when collapsed (default), or N wrapped rows
    # when expanded. Flash adds one row above the hints when present.
    if hints_collapsed:
        hint_lines: list[str] = [" ? Hints  (Press ? to Expand)"]
    else:
        hint_lines = [" " + ln for ln in _wrap_hints(_HINT_CHUNKS, max(1, w - 2))]
    hint_h     = len(hint_lines)
    footer_h   = 2 + hint_h + (1 if flash else 0)
    # Header rows (always banner): divider (0) → marquee (1) →
    # divider (2) → blank (3) → title (4) → blank (5) → divider (6);
    # first section starts at 7.
    middle_top = 7
    middle_bottom = h - bottom_h - footer_h
    middle_h   = max(0, middle_bottom - middle_top)

    # 1 row per separator between sections (header gets a separator row above it
    # except for the first). Reserve those before allocating to sections.
    n_seps    = max(0, len(sections) - 1)
    avail     = max(0, middle_h - n_seps)
    rows_per  = _allocate_section_rows(
        sections, avail, collapsed=collapsed, size_mult=size_mult,
    )

    # Roles section auto-scrolls to keep the selected role visible —
    # but skip when the section is collapsed; otherwise the offset
    # would move off the header row and hide the section name.
    for i, sec in enumerate(sections):
        if sec["id"] != "roles":
            continue
        if collapsed.get("roles", False):
            section_offsets["roles"] = 0
            continue
        sl = sec["sel_local"]
        if sl < 0 or rows_per[i] <= 0:
            continue
        off = section_offsets.get("roles", 0)
        if sl < off:
            section_offsets["roles"] = sl
        elif sl >= off + rows_per[i]:
            section_offsets["roles"] = sl - rows_per[i] + 1

    # Render sections top-to-bottom, tracking each one's row range and
    # the row of its header (for collapse-toggle click handling).
    row = middle_top
    section_rows: dict[str, tuple[int, int]] = {}
    header_rows: dict[str, int] = {}
    for i, sec in enumerate(sections):
        if i > 0 and row < middle_bottom:
            _put(stdscr, row, h, w, "─" * (w - 1), C["DIM"])
            row += 1
        sec_h = rows_per[i]
        if sec_h <= 0 or row >= middle_bottom:
            continue
        max_off = max(0, len(sec["lines"]) - sec_h)
        off = max(0, min(section_offsets.get(sec["id"], 0), max_off))
        section_offsets[sec["id"]] = off
        start_row = row
        # Header is the first line of the section's `lines` list. When the
        # section's offset is 0 the header sits at start_row; otherwise the
        # header has scrolled out of view and we record -1 to disable
        # collapse-click hit-testing.
        header_rows[sec["id"]] = start_row if off == 0 else -1
        for j in range(sec_h):
            if row >= middle_bottom:
                break
            idx = off + j
            if idx >= len(sec["lines"]):
                row += 1
                continue
            text, attr = sec["lines"][idx]
            if text == _SEP_MARKER:
                _put(stdscr, row, h, w, "─" * (w - 1), attr)
            else:
                put(row, text, attr)
            row += 1
        # Scroll indicators (overwrite the first/last row of the section).
        # Skip when collapsed — the section is just the header row, and
        # overwriting it with ▼ would hide the section name.
        is_collapsed = collapsed.get(sec["id"], False)
        if not is_collapsed:
            if off > 0 and start_row < middle_bottom:
                put(start_row, "▲" + " " * (w - 2), C["YLW"])
            if off + sec_h < len(sec["lines"]) and (start_row + sec_h - 1) < middle_bottom:
                put(start_row + sec_h - 1, "▼" + " " * (w - 2), C["YLW"])
        section_rows[sec["id"]] = (start_row, start_row + sec_h)

    # Bottom-anchored resources block (also scrollable as its own section).
    res_start = middle_bottom
    for i, (text, attr) in enumerate(bottom_lines):
        r = res_start + i
        if r >= h - footer_h:
            break
        if text == _SEP_MARKER:
            _put(stdscr, r, h, w, "─" * (w - 1), attr)
        else:
            put(r, text, attr)
    if bottom_h > 0:
        section_rows["resources"] = (res_start, min(res_start + bottom_h, h - footer_h))

    # Footer block (bottom-up): divider (h-1), hints (h-2), divider (h-3),
    # optional flash (h-4 when present).
    _sep(stdscr, h - 1, h, w, C["DIM"])
    # Hint rows occupy h-2 down to h-1-hint_h.
    for i, ln in enumerate(hint_lines):
        put(h - 1 - hint_h + i, ln, C["DIM"])
    _sep(stdscr, h - 2 - hint_h, h, w, C["DIM"])
    if flash:
        put(h - 3 - hint_h, f" {flash}", C["HEAD"])
    stdscr.refresh()
    return section_rows, header_rows


# ── submenu view ──────────────────────────────────────────────────────────────

def _draw_submenu(stdscr, role: str, info: dict, sel: int, C: dict) -> None:
    h, w = stdscr.getmaxyx()
    def put(r, t, a=0):
        return _put(stdscr, r, h, w, t, a)
    stdscr.erase()

    alive  = info.get("alive", False)
    status = f"running  pid {info['pid']}" if alive else "STOPPED"
    status_attr = (C["HEAD"] | curses.A_BOLD) if alive else (C["ERR"] | curses.A_BOLD)
    put(0, f" {role}  [ {status} ]", status_attr)
    _sep(stdscr, 1, h, w, C["DIM"])

    for i, action in enumerate(_ACTIONS):
        if i == sel:
            put(i + 2, f"  ▶ {action}", C["SEL"] | curses.A_BOLD)
        else:
            put(i + 2, f"    {action}", 0)

    _sep(stdscr, len(_ACTIONS) + 2, h, w, C["DIM"])
    put(h - 1, " ↑↓ Select  ↵ Run  Esc Back", C["DIM"])
    stdscr.refresh()


# ── log view ──────────────────────────────────────────────────────────────────

def _draw_log_view(stdscr, role: str, lines: list[str], C: dict) -> None:
    h, w = stdscr.getmaxyx()
    def put(r, t, a=0):
        return _put(stdscr, r, h, w, t, a)
    stdscr.erase()

    put(0, f" Circuit Breaker — {role} (Last {LOG_TAIL_LINES} Lines)", C["HEAD"] | curses.A_BOLD)
    _sep(stdscr, 1, h, w, C["DIM"])

    for i, line in enumerate(lines[-(h - 3):]):
        put(i + 2, f" {line}", C["DIM"])

    put(h - 1, " Esc Back", C["DIM"])
    stdscr.refresh()


# ── actions ───────────────────────────────────────────────────────────────────

def _do_tail(role: str) -> str:
    log = _latest_log(role)
    if not log:
        return f"no log found for {role}"
    curses.endwin()
    os.execvp("tail", ["tail", "-f", str(log)])
    return ""


def _do_board() -> str:
    url = os.environ.get("OPERATIONS_CENTER_PLANE_URL", "").strip()
    if not url:
        return "set OPERATIONS_CENTER_PLANE_URL to enable board"
    try:
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return "xdg-open failed"
    return f"opened {url[:50]}"


def _do_memory(info: dict) -> None:
    pid = info.get("pid", "")
    curses.endwin()
    if pid and _pid_alive(pid):
        os.execvp("htop", ["htop", "-p", pid])
    else:
        os.execvp("htop", ["htop"])


def _read_log_lines(role: str) -> list[str]:
    log = _latest_log(role)
    if not log:
        return ["(no log file found)"]
    try:
        return log.read_text(encoding="utf-8", errors="replace").splitlines()[-LOG_TAIL_LINES:]
    except Exception as e:
        return [f"(error: {e})"]


# ── main pane ─────────────────────────────────────────────────────────────────

def _pane(stdscr, profile_name: str) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN,  -1)
    curses.init_pair(2, curses.COLOR_WHITE,  -1)
    curses.init_pair(3, curses.COLOR_CYAN,   -1)
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(5, curses.COLOR_YELLOW, -1)
    curses.init_pair(6, curses.COLOR_RED,    -1)
    # Banner pairs — explicit white-on-color for the marquee banners.
    curses.init_pair(7,  curses.COLOR_WHITE, curses.COLOR_RED)     # CRITICAL
    curses.init_pair(8,  curses.COLOR_WHITE, curses.COLOR_YELLOW)  # WARNING
    curses.init_pair(9,  curses.COLOR_WHITE, curses.COLOR_GREEN)   # HEALTHY
    curses.init_pair(10, curses.COLOR_WHITE, curses.COLOR_CYAN)    # INFO

    C = {
        "RUN":  curses.color_pair(1),
        "DIM":  curses.color_pair(2) | curses.A_DIM,
        "HEAD": curses.color_pair(3),
        "SEL":  curses.color_pair(4),
        "YLW":  curses.color_pair(5),
        "ERR":  curses.color_pair(6),
        "BANNER_CRIT":    curses.color_pair(7),
        "BANNER_WARN":    curses.color_pair(8),
        "BANNER_HEALTHY": curses.color_pair(9),
        "BANNER_INFO":    curses.color_pair(10),
    }

    repo_filter = _profile_repos(profile_name) if profile_name else None

    _empty_roles = {r: {"alive": False, "pid": "", "mtime": None} for r in _ROLES}
    data: dict = {
        "roles": dict(_empty_roles), "restarts": {}, "campaigns": [],
        "sb": False, "queue": [], "resources": {}, "at": time.time(),
    }
    refreshing = False
    lock = threading.Lock()

    def _refresh_loop() -> None:
        nonlocal refreshing
        while True:
            refreshing = True
            fresh = _collect(repo_filter)
            with lock:
                data.update(fresh)
            refreshing = False
            time.sleep(REFRESH_INTERVAL)

    threading.Thread(target=_refresh_loop, daemon=True).start()
    with lock:
        data.update(_collect(repo_filter))

    # 200ms tick when a stall banner is streaming, 500ms otherwise. The
    # value is reset each iteration based on whether the banner is up.
    _BANNER_TICK_MS = 200
    _IDLE_TICK_MS = 500
    stdscr.timeout(_IDLE_TICK_MS)
    # Mouse: enable wheel + click. mouseinterval(0) disables click-debounce
    # so wheel events fire as fast as the terminal sends them.
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.mouseinterval(0)
    except curses.error:
        pass  # Terminal without mouse support — keyboard still works.

    role_sel    = 0
    mode        = "roles"
    action_sel  = 0
    log_lines: list[str] = []
    flash       = ""
    flash_at    = 0.0
    # Per-section scroll offsets. Persists across refreshes so a section
    # that's been scrolled stays scrolled when the data updates.
    section_offsets: dict[str, int] = {}
    # Last rendered section row ranges — used by mouse-wheel events to
    # find which section the cursor is hovering over.
    section_rows: dict[str, tuple[int, int]] = {}
    header_rows: dict[str, int] = {}
    # The "focused" section — what PgUp/PgDn target. Defaults to 'roles';
    # mouse-wheel events update this so subsequent keyboard scrolling
    # follows the cursor.
    focused_section = "roles"
    # Banner is always rendered now (HEALTHY when nothing is wrong).
    # Marquee offset advances every frame; cycle index advances every
    # _BANNER_CYCLE_FRAMES frames so each condition gets a steady
    # readable window before the next one rotates in.
    banner_offset = 0
    banner_index = 0
    banner_frame_count = 0
    pane_started_at = time.time()
    _BANNER_CYCLE_FRAMES = 15  # at 200ms tick → 3s per condition
    # Collapsed sections show only their header row; +/- resize scales the
    # focused section's natural row count up or down. Default everything
    # collapsed so the pane opens compact — operators expand what they
    # need with click-on-header or `c`. (System Resources is bottom-
    # anchored, not part of the collapsible section set.)
    collapsed_sections: dict[str, bool] = {
        sid: True for sid in (
            "roles", "active", "recent", "board",
            "campaigns", "queue", "budget", "backend_caps", "services",
        )
    }
    size_mult: dict[str, float] = {}
    # Hint bar starts collapsed — operators toggle with `?`.
    hints_collapsed = True

    while True:
        if flash and time.time() - flash_at > 2:
            flash = ""

        with lock:
            snap = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
                    for k, v in data.items()}

        # Banner conditions — always at least one entry (HEALTHY).
        # Cycle index advances every _BANNER_CYCLE_FRAMES so each
        # condition holds the screen long enough to read.
        conditions = _banner_conditions(snap, pane_started_at)
        if banner_index >= len(conditions):
            banner_index = 0
        current_banner = conditions[banner_index]

        if mode == "log":
            _draw_log_view(stdscr, _ROLES[role_sel], log_lines, C)
        elif mode == "action":
            _draw_submenu(stdscr, _ROLES[role_sel],
                          snap["roles"].get(_ROLES[role_sel], {}), action_sel, C)
        else:
            section_rows, header_rows = _draw_main(
                stdscr, snap, role_sel, refreshing, flash, C, section_offsets,
                collapsed=collapsed_sections,
                size_mult=size_mult,
                focused_section=focused_section,
                banner_offset=banner_offset,
                current_banner=current_banner,
                banner_count=len(conditions),
                banner_index=banner_index,
                hints_collapsed=hints_collapsed,
            )

        # Marquee + cycle bookkeeping. Banner always animates; tick at
        # the faster cadence so the scroll reads smoothly regardless of
        # severity.
        banner_offset += 2
        banner_frame_count += 1
        if banner_frame_count >= _BANNER_CYCLE_FRAMES and len(conditions) > 1:
            banner_index = (banner_index + 1) % len(conditions)
            banner_frame_count = 0
            banner_offset = 0  # restart marquee for the next condition
        stdscr.timeout(_BANNER_TICK_MS)

        key = stdscr.getch()

        if mode == "log":
            if key in (27, ord("q"), ord("b")):
                mode = "roles"

        elif mode == "action":
            if key == curses.KEY_UP:
                action_sel = (action_sel - 1) % len(_ACTIONS)
            elif key == curses.KEY_DOWN:
                action_sel = (action_sel + 1) % len(_ACTIONS)
            elif key in (27, ord("b")):
                mode = "roles"
            elif key in (curses.KEY_ENTER, 10, 13):
                action = _ACTIONS[action_sel]
                role   = _ROLES[role_sel]
                if action == "tail logs":
                    msg = _do_tail(role)
                    flash = msg
                    flash_at = time.time()
                    mode = "roles"
                elif action == "board":
                    flash = _do_board()
                    flash_at = time.time()
                    mode = "roles"
                elif action == "circuit breaker":
                    log_lines = _read_log_lines(role)
                    mode = "log"
                elif action == "memory":
                    _do_memory(snap["roles"].get(role, {}))

        else:
            if key == curses.KEY_UP:
                role_sel = (role_sel - 1) % len(_ROLES)
            elif key == curses.KEY_DOWN:
                role_sel = (role_sel + 1) % len(_ROLES)
            elif key == curses.KEY_PPAGE:
                # Scroll the focused section up by half its visible rows.
                if focused_section in section_rows:
                    s, e = section_rows[focused_section]
                    section_offsets[focused_section] = max(
                        0, section_offsets.get(focused_section, 0) - max(1, (e - s) // 2),
                    )
            elif key == curses.KEY_NPAGE:
                if focused_section in section_rows:
                    s, e = section_rows[focused_section]
                    section_offsets[focused_section] = (
                        section_offsets.get(focused_section, 0) + max(1, (e - s) // 2)
                    )
            elif key == curses.KEY_HOME:
                section_offsets[focused_section] = 0
            elif key == curses.KEY_END:
                section_offsets[focused_section] = 10_000  # clamped on next render
            elif key == ord("+"):
                cur = size_mult.get(focused_section, 1.0)
                size_mult[focused_section] = min(
                    _SIZE_MULT_MAX, cur + _SIZE_MULT_STEP,
                )
            elif key == ord("-"):
                cur = size_mult.get(focused_section, 1.0)
                size_mult[focused_section] = max(
                    _SIZE_MULT_MIN, cur - _SIZE_MULT_STEP,
                )
            elif key == ord("="):
                size_mult.pop(focused_section, None)
            elif key == ord("c"):
                collapsed_sections[focused_section] = not collapsed_sections.get(
                    focused_section, False,
                )
            elif key == curses.KEY_MOUSE:
                # Wheel events: BUTTON4=up, BUTTON5=down. Map mouse y to
                # the section under the cursor and bump that section's
                # offset by 3 lines (typical wheel step).
                try:
                    _, _mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    bstate = 0
                    my = -1
                target_section = None
                for sec_id, (s, e) in section_rows.items():
                    if s <= my < e:
                        target_section = sec_id
                        break
                if target_section is not None:
                    focused_section = target_section
                    if bstate & curses.BUTTON4_PRESSED:
                        section_offsets[target_section] = max(
                            0, section_offsets.get(target_section, 0) - 3,
                        )
                    elif bstate & curses.BUTTON5_PRESSED:
                        section_offsets[target_section] = (
                            section_offsets.get(target_section, 0) + 3
                        )
                    elif bstate & curses.BUTTON1_PRESSED:
                        # Click on a section's header row toggles collapse.
                        hdr_row = header_rows.get(target_section, -1)
                        if hdr_row >= 0 and my == hdr_row:
                            collapsed_sections[target_section] = not (
                                collapsed_sections.get(target_section, False)
                            )
            elif key in (curses.KEY_ENTER, 10, 13):
                mode = "action"
                action_sel = 0
            elif key == ord("?"):
                hints_collapsed = not hints_collapsed
            elif key == ord("r"):
                with lock:
                    data.update({"roles": dict(_empty_roles), "campaigns": [],
                                 "sb": False, "queue": [], "resources": {}})
            elif key in (ord("q"), 27):
                break


def main() -> None:
    profile_name = ""
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--profile" and i + 1 < len(args):
            profile_name = args[i + 1]
    curses.wrapper(_pane, profile_name)


if __name__ == "__main__":
    main()
