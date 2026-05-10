# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velascat
from __future__ import annotations

from pathlib import Path

from operator_console.bootstrap import get_codex_command


def _script_text(command: str) -> str:
    prefix = "bash '"
    assert command.startswith(prefix)
    path = command[len(prefix):-1]
    return Path(path).read_text(encoding="utf-8")


def test_codex_startup_defaults_to_full_access() -> None:
    command = get_codex_command({"name": "TestRepo"}, Path("/tmp/repo"))
    script = _script_text(command)

    assert "'codex' -a never -s danger-full-access resume --last" in script
    assert "|| 'codex' -a never -s danger-full-access" in script


def test_codex_startup_can_use_profile_defaults() -> None:
    command = get_codex_command(
        {
            "name": "TestRepoDefaults",
            "codex": {"approval_mode": "", "sandbox_mode": ""},
        },
        Path("/tmp/repo"),
    )
    script = _script_text(command)

    assert "-a never" not in script
    assert "danger-full-access" not in script
    assert "'codex' resume --last" in script
