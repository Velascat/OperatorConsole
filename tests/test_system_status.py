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
