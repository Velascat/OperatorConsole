# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velascat
"""Tests for watcher_status_pane: data collectors, allocator, CLI wiring."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


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

    def test_resource_gate_parses_block(self, tmp_path, monkeypatch):
        from operator_console import watcher_status_pane as wsp
        cfg = tmp_path / "operations_center.local.yaml"
        cfg.write_text(
            "kodo:\n"
            "  binary: kodo\n"
            "resource_gate:\n"
            "  max_concurrent: 6              # leave headroom for co-tenants\n"
            "  min_available_memory_mb: 12288 # reserve 12 GiB\n"
            "archon:\n"
            "  enabled: false\n"
        )
        monkeypatch.setattr(wsp, "_OC_CONFIG", cfg)
        assert wsp._resource_gate() == {
            "max_concurrent": 6,
            "min_available_memory_mb": 12288,
        }

    def test_resource_gate_missing_block_returns_empty(
        self, tmp_path, monkeypatch,
    ):
        from operator_console import watcher_status_pane as wsp
        cfg = tmp_path / "operations_center.local.yaml"
        cfg.write_text("kodo:\n  binary: kodo\n")
        monkeypatch.setattr(wsp, "_OC_CONFIG", cfg)
        assert wsp._resource_gate() == {}

    def test_resource_gate_missing_file(self, tmp_path, monkeypatch):
        from operator_console import watcher_status_pane as wsp
        monkeypatch.setattr(wsp, "_OC_CONFIG", tmp_path / "missing.yaml")
        assert wsp._resource_gate() == {}


class TestSectionAllocator:
    def test_natural_height_fits(self):
        from operator_console.watcher_status_pane import _allocate_section_rows
        sections = [
            {"id": "a", "lines": [("h", 0), ("a1", 0), ("a2", 0)]},
            {"id": "b", "lines": [("h", 0), ("b1", 0)]},
        ]
        out = _allocate_section_rows(sections, 20)
        assert out == [3, 2]

    def test_overflow_proportional(self):
        from operator_console.watcher_status_pane import _allocate_section_rows
        sections = [
            {"id": "a", "lines": [("h", 0)] + [(f"a{i}", 0) for i in range(20)]},
            {"id": "b", "lines": [("h", 0)] + [(f"b{i}", 0) for i in range(20)]},
        ]
        out = _allocate_section_rows(sections, 10)
        assert sum(out) <= 10
        assert min(out) >= 3
        assert abs(out[0] - out[1]) <= 1

    def test_empty_sections_get_zero(self):
        from operator_console.watcher_status_pane import _allocate_section_rows
        sections = [
            {"id": "a", "lines": [("h", 0)]},
            {"id": "empty", "lines": []},
        ]
        out = _allocate_section_rows(sections, 10)
        assert out[1] == 0

    def test_zero_available_returns_zeros(self):
        from operator_console.watcher_status_pane import _allocate_section_rows
        sections = [{"id": "a", "lines": [("h", 0), ("x", 0)]}]
        assert _allocate_section_rows(sections, 0) == [0]

    def test_collapsed_section_gets_one_row(self):
        from operator_console.watcher_status_pane import _allocate_section_rows
        sections = [
            {"id": "a", "lines": [("h", 0), ("a1", 0), ("a2", 0), ("a3", 0)]},
            {"id": "b", "lines": [("h", 0), ("b1", 0), ("b2", 0)]},
        ]
        out = _allocate_section_rows(
            sections, 20, collapsed={"a": True},
        )
        assert out[0] == 1
        assert out[1] == 3

    def test_size_mult_grows_natural_height(self):
        from operator_console.watcher_status_pane import _allocate_section_rows
        sections = [
            {"id": "a", "lines": [("h", 0), ("a1", 0)]},
            {"id": "b", "lines": [("h", 0), ("b1", 0)]},
        ]
        out = _allocate_section_rows(
            sections, 20, size_mult={"a": 2.0},
        )
        assert out == [4, 2]

    def test_collapsed_during_overflow(self):
        from operator_console.watcher_status_pane import _allocate_section_rows
        sections = [
            {"id": "a", "lines": [("h", 0)] + [(f"a{i}", 0) for i in range(30)]},
            {"id": "b", "lines": [("h", 0)] + [(f"b{i}", 0) for i in range(30)]},
        ]
        out = _allocate_section_rows(
            sections, 10, collapsed={"a": True},
        )
        assert out[0] == 1
        assert out[1] <= 9
        assert sum(out) <= 10


class TestStatusCli:
    def test_status_default_routes_to_watcher(self):
        from pathlib import Path
        cli_src = Path(
            __import__("operator_console.cli", fromlist=["__file__"]).__file__,
        ).read_text()
        # `console status` (no flags) should resolve to the watcher entry.
        assert "from operator_console.watcher_status_pane import main as _w" in cli_src

    def test_system_status_module_removed(self):
        import importlib
        try:
            importlib.import_module("operator_console.system_status")
        except ImportError:
            return
        raise AssertionError(
            "operator_console.system_status should be deleted — watcher owns status"
        )
