# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velascat
"""Tests for system_status helpers (budget + resources)."""
from __future__ import annotations

import json
from pathlib import Path

from operator_console import system_status as ss


class TestOcBudget:
    def test_reads_usage_json_and_caps(self, tmp_path, monkeypatch):
        # Stub the repo-root resolver so the helper reads from tmp_path.
        target = tmp_path / "OperationsCenter" / "tools" / "report" / \
            "operations_center" / "execution"
        target.mkdir(parents=True)
        (target / "usage.json").write_text(json.dumps({
            "hourly_exec_count": 7,
            "daily_exec_count": 33,
        }))
        monkeypatch.setattr(
            ss, "_repo_root",
            lambda name: tmp_path / name,
        )
        monkeypatch.setenv("OPERATIONS_CENTER_MAX_EXEC_PER_HOUR", "12")
        monkeypatch.setenv("OPERATIONS_CENTER_MAX_EXEC_PER_DAY", "60")

        b = ss._oc_budget()
        assert b["found"] is True
        assert b["hourly_used"] == 7
        assert b["daily_used"] == 33
        assert b["hourly_cap"] == 12
        assert b["daily_cap"] == 60

    def test_missing_usage_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "_repo_root", lambda name: tmp_path / name)
        b = ss._oc_budget()
        assert b["found"] is False
        assert b["hourly_used"] == 0
        assert b["daily_used"] == 0
        # Caps are populated from defaults even when usage.json is missing.
        assert b["hourly_cap"] >= 1
        assert b["daily_cap"] >= 1

    def test_malformed_usage_file_falls_back(self, tmp_path, monkeypatch):
        target = tmp_path / "OperationsCenter" / "tools" / "report" / \
            "operations_center" / "execution"
        target.mkdir(parents=True)
        (target / "usage.json").write_text("{not json")
        monkeypatch.setattr(ss, "_repo_root", lambda name: tmp_path / name)
        b = ss._oc_budget()
        assert b["found"] is False
        assert b["hourly_used"] == 0
        assert b["daily_used"] == 0


class TestProcCount:
    def test_returns_positive_int_on_linux(self):
        # /proc exists on Linux (incl. WSL2). Don't assert exact count.
        if Path("/proc").is_dir():
            assert ss._proc_count() > 0
        else:
            assert ss._proc_count() == 0


class TestMemorySummary:
    def test_returns_expected_keys(self):
        m = ss._memory_summary()
        for key in (
            "mem_total_mb", "mem_used_mb", "mem_available_mb",
            "swap_total_mb", "swap_used_mb", "swap_free_mb",
            "low_mem_threshold_mb",
        ):
            assert key in m, f"missing key: {key}"
            assert isinstance(m[key], int)
        # On Linux MemTotal must be present and positive.
        if Path("/proc/meminfo").exists():
            assert m["mem_total_mb"] > 0
            assert m["mem_used_mb"] >= 0
            assert m["mem_used_mb"] <= m["mem_total_mb"]
            assert m["mem_available_mb"] >= 0
        # OC's kodo dispatch threshold (default 6144 MB).
        assert m["low_mem_threshold_mb"] == 6144


class TestStatusJsonShape:
    def test_json_includes_new_sections(self, capsys, monkeypatch):
        # Avoid HTTP probes hanging the test.
        monkeypatch.setattr(ss, "_http_ok", lambda url: False)
        monkeypatch.setattr(ss, "_which", lambda b: False)
        monkeypatch.setattr(ss, "_watcher_status", lambda: {})
        from operator_console import runs as runs_mod
        monkeypatch.setattr(runs_mod, "latest_run", lambda: None)

        rc = ss.run_status(["--json"])
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert "execution_budget" in payload
        assert "system" in payload
        assert "process_count" in payload["system"]
        assert "memory" in payload["system"]
        assert "low_mem_threshold_mb" in payload["system"]["memory"]
        # Exit code can be 0 or 1 depending on overall_ok; we don't care.
        assert rc in (0, 1)


# ---------------------------------------------------------------------------
# Per-backend caps + per-backend usage rendering (task #32)
# ---------------------------------------------------------------------------


class TestOcBackendCaps:
    def test_reads_backend_caps_from_local_yaml(self, tmp_path, monkeypatch):
        repo = tmp_path / "OperationsCenter"
        cfg = repo / "config"
        cfg.mkdir(parents=True)
        (cfg / "operations_center.local.yaml").write_text(
            "backend_caps:\n"
            "  kodo:\n"
            "    min_available_memory_mb: 6144\n"
            "    max_concurrent: 1\n"
            "  archon:\n"
            "    max_per_day: 5\n"
            "    max_concurrent: 4\n"
        )
        monkeypatch.setattr(ss, "_repo_root", lambda name: tmp_path / name)
        caps = ss._oc_backend_caps()
        assert caps["kodo"] == {"min_available_memory_mb": 6144, "max_concurrent": 1}
        assert caps["archon"] == {"max_per_day": 5, "max_concurrent": 4}

    def test_missing_yaml_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "_repo_root", lambda name: tmp_path / name)
        assert ss._oc_backend_caps() == {}


class TestOcBackendUsage:
    def test_aggregates_per_backend_counters(self, tmp_path, monkeypatch):
        from datetime import datetime, timezone, timedelta
        target = tmp_path / "OperationsCenter" / "tools" / "report" / \
            "operations_center" / "execution"
        target.mkdir(parents=True)
        now = datetime.now(timezone.utc)
        events = [
            # Two execution events for archon — one in last hour, one in last day
            {"kind": "execution", "backend": "archon",
             "timestamp": (now - timedelta(minutes=5)).isoformat()},
            {"kind": "execution", "backend": "archon",
             "timestamp": (now - timedelta(hours=8)).isoformat()},
            # One in-flight kodo (started, no finished)
            {"kind": "execution_started", "backend": "kodo", "task_id": "k1",
             "timestamp": (now - timedelta(minutes=2)).isoformat()},
            # Kodo started+finished — not in flight
            {"kind": "execution_started", "backend": "kodo", "task_id": "k2",
             "timestamp": (now - timedelta(hours=1)).isoformat()},
            {"kind": "execution_finished", "backend": "kodo", "task_id": "k2",
             "timestamp": (now - timedelta(minutes=30)).isoformat()},
            # Stale archon execution → should NOT count toward daily
            {"kind": "execution", "backend": "archon",
             "timestamp": (now - timedelta(days=2)).isoformat()},
            # Untagged event — ignored
            {"kind": "execution",
             "timestamp": (now - timedelta(minutes=5)).isoformat()},
        ]
        (target / "usage.json").write_text(
            json.dumps({"events": events})
        )
        monkeypatch.setattr(ss, "_repo_root", lambda name: tmp_path / name)
        u = ss._oc_backend_usage()
        assert u["archon"]["hourly"] == 1
        assert u["archon"]["daily"] == 2
        assert u["archon"]["in_flight"] == 0
        assert u["kodo"]["in_flight"] == 1
        assert u["kodo"].get("hourly", 0) == 0  # only execution events count

    def test_missing_usage_json_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "_repo_root", lambda name: tmp_path / name)
        assert ss._oc_backend_usage() == {}


class TestStatusJsonShapeIncludesBackends:
    def test_json_payload_has_backend_keys(self, capsys, monkeypatch):
        monkeypatch.setattr(ss, "_http_ok", lambda url: False)
        monkeypatch.setattr(ss, "_which", lambda b: False)
        monkeypatch.setattr(ss, "_watcher_status", lambda: {})
        monkeypatch.setattr(ss, "_oc_backend_caps", lambda: {"kodo": {"max_concurrent": 1}})
        monkeypatch.setattr(ss, "_oc_backend_usage", lambda: {"kodo": {"hourly": 0, "daily": 2, "in_flight": 1}})
        from operator_console import runs as runs_mod
        monkeypatch.setattr(runs_mod, "latest_run", lambda: None)

        ss.run_status(["--json"])
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["backend_caps"] == {"kodo": {"max_concurrent": 1}}
        assert payload["backend_usage"] == {"kodo": {"hourly": 0, "daily": 2, "in_flight": 1}}


# ---------------------------------------------------------------------------
# Curses pane data collectors (watcher_status_pane.py)
# ---------------------------------------------------------------------------


class TestCursesPaneCollectors:
    def test_exec_budget_reads_usage(self, tmp_path, monkeypatch):
        from operator_console import watcher_status_pane as wsp
        target = tmp_path / "tools" / "report" / "operations_center" / "execution"
        target.mkdir(parents=True)
        (target / "usage.json").write_text(
            json.dumps({"hourly_exec_count": 7, "daily_exec_count": 33})
        )
        monkeypatch.setattr(wsp, "_USAGE_PATH", target / "usage.json")
        monkeypatch.setenv("OPERATIONS_CENTER_MAX_EXEC_PER_HOUR", "12")
        monkeypatch.setenv("OPERATIONS_CENTER_MAX_EXEC_PER_DAY", "60")
        b = wsp._exec_budget()
        assert b == {
            "found": True, "hourly_used": 7, "hourly_cap": 12,
            "daily_used": 33, "daily_cap": 60,
        }

    def test_exec_budget_missing_file(self, tmp_path, monkeypatch):
        from operator_console import watcher_status_pane as wsp
        monkeypatch.setattr(wsp, "_USAGE_PATH", tmp_path / "missing.json")
        b = wsp._exec_budget()
        assert b["found"] is False
        assert b["hourly_used"] == 0

    def test_backend_caps_parses_indented_block_with_inline_comments(
        self, tmp_path, monkeypatch,
    ):
        from operator_console import watcher_status_pane as wsp
        cfg = tmp_path / "operations_center.local.yaml"
        cfg.write_text(
            "kodo:\n"
            "  binary: kodo\n"
            "backend_caps:\n"
            "  kodo:\n"
            "    min_available_memory_mb: 6144   # subprocess team config\n"
            "    max_concurrent: 1               # teams hate sharing\n"
            "  archon:\n"
            "    max_per_day: 5\n"
            "    max_concurrent: 4\n"
            "archon:\n"
            "  enabled: false\n"
        )
        monkeypatch.setattr(wsp, "_OC_CONFIG", cfg)
        caps = wsp._backend_caps()
        assert caps == {
            "kodo": {"min_available_memory_mb": 6144, "max_concurrent": 1},
            "archon": {"max_per_day": 5, "max_concurrent": 4},
        }

    def test_backend_caps_missing_file(self, tmp_path, monkeypatch):
        from operator_console import watcher_status_pane as wsp
        monkeypatch.setattr(wsp, "_OC_CONFIG", tmp_path / "missing.yaml")
        assert wsp._backend_caps() == {}

    def test_backend_usage_aggregates_per_backend_counters(
        self, tmp_path, monkeypatch,
    ):
        from operator_console import watcher_status_pane as wsp
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        events = [
            {"kind": "execution", "backend": "archon",
             "timestamp": (now - timedelta(minutes=5)).isoformat()},
            {"kind": "execution", "backend": "archon",
             "timestamp": (now - timedelta(hours=8)).isoformat()},
            {"kind": "execution_started", "backend": "kodo", "task_id": "k1",
             "timestamp": (now - timedelta(minutes=2)).isoformat()},
            {"kind": "execution_started", "backend": "kodo", "task_id": "k2",
             "timestamp": (now - timedelta(hours=1)).isoformat()},
            {"kind": "execution_finished", "backend": "kodo", "task_id": "k2",
             "timestamp": (now - timedelta(minutes=30)).isoformat()},
        ]
        path = tmp_path / "usage.json"
        path.write_text(json.dumps({"events": events}))
        monkeypatch.setattr(wsp, "_USAGE_PATH", path)
        u = wsp._backend_usage()
        assert u["archon"]["hourly"] == 1
        assert u["archon"]["daily"] == 2
        assert u["archon"]["in_flight"] == 0
        assert u["kodo"]["in_flight"] == 1

    def test_backend_usage_missing_file(self, tmp_path, monkeypatch):
        from operator_console import watcher_status_pane as wsp
        monkeypatch.setattr(wsp, "_USAGE_PATH", tmp_path / "missing.json")
        assert wsp._backend_usage() == {}
