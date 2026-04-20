"""Zellij session creation and attachment."""
from __future__ import annotations
import os
import subprocess
import tempfile
from pathlib import Path

from fob.session import session_exists
from fob.guardrails import check_branch
from fob.bootstrap import get_claude_command

FOB_SESSION = "fob"
_GITHUB_DIR = Path.home() / "Documents" / "GitHub"

_C = {"R": "\033[0m", "DIM": "\033[2m", "GRN": "\033[32m", "YLW": "\033[33m"}


def _c(text: str, *keys: str) -> str:
    return "".join(_C[k] for k in keys) + text + _C["R"]


# ── single-repo pane block ────────────────────────────────────────────────────
#
#  Left 35% stacked: lazygit, logs
#  Right 65% horizontal split:
#    ├── claude  (~85%)
#    └── shell   (15%)

def _single_pane_block(
    profile: dict,
    fob_dir: Path,
    indent: str = "        ",
    claude_cwd: Path | None = None,
) -> str:
    repo      = profile["repo_root"]
    panes_cfg = profile.get("panes", {})
    claude_cmd = get_claude_command(profile, Path(repo))
    git_cmd   = panes_cfg.get("git",  {}).get("command", "lazygit")
    logs_cmd  = panes_cfg.get("logs", {}).get(
        "command", "tail -f .fob/runtime.log 2>/dev/null || echo 'No runtime.log yet'",
    )
    safe_repo = repo.replace("'", "'\\''")
    safe_cwd  = str(claude_cwd).replace("'", "'\\''") if claude_cwd else safe_repo
    welcome   = str(fob_dir / "tools" / "welcome.sh").replace("'", "'\\''")
    i = indent

    return (
        f'{i}pane split_direction="vertical" {{\n'
        f'{i}    pane size="35%" stacked=true {{\n'
        f'{i}        pane name="git" command="bash" {{\n'
        f'{i}            args "-c" "cd \'{safe_repo}\' && {git_cmd}; exec bash -l"\n'
        f'{i}        }}\n'
        f'{i}        pane name="logs" command="bash" {{\n'
        f'{i}            args "-c" "cd \'{safe_repo}\' && {logs_cmd}; exec bash -l"\n'
        f'{i}        }}\n'
        f'{i}    }}\n'
        f'{i}    pane split_direction="horizontal" {{\n'
        f'{i}        pane name="claude" command="bash" {{\n'
        f'{i}            args "-c" "cd \'{safe_cwd}\' && {claude_cmd}"\n'
        f'{i}        }}\n'
        f'{i}        pane size="15%" name="shell" command="bash" {{\n'
        f'{i}            args "-c" "cd \'{safe_cwd}\' && bash \'{welcome}\'"\n'
        f'{i}        }}\n'
        f'{i}    }}\n'
        f'{i}}}'
    )


# ── multi-repo pane block ─────────────────────────────────────────────────────
#
#  Repos split left/right (even indices left, odd indices right).
#  Each side: per-repo lazygit+logs stacked.
#  Center horizontal split:
#    ├── claude  (~85%)  — starts at ~/Documents/GitHub/
#    └── shell   (15%)   — starts at ~/Documents/GitHub/

def _repo_stack_panes(profiles: list[dict], indent: str) -> str:
    """lazygit + logs panes for each profile, to be placed inside a stacked parent."""
    out = ""
    i = indent
    for p in profiles:
        repo     = p["repo_root"].replace("'", "'\\''")
        git_cmd  = p.get("panes", {}).get("git",  {}).get("command", "lazygit")
        logs_cmd = p.get("panes", {}).get("logs", {}).get(
            "command", "tail -f .fob/runtime.log 2>/dev/null || echo 'No runtime.log yet'",
        )
        out += (
            f'{i}pane name="git-{p["name"]}" command="bash" {{\n'
            f'{i}    args "-c" "cd \'{repo}\' && {git_cmd}; exec bash -l"\n'
            f'{i}}}\n'
            f'{i}pane name="logs-{p["name"]}" command="bash" {{\n'
            f'{i}    args "-c" "cd \'{repo}\' && {logs_cmd}; exec bash -l"\n'
            f'{i}}}\n'
        )
    return out


def _multi_pane_block(
    profiles: list[dict],
    fob_dir: Path,
    indent: str = "        ",
) -> str:
    left  = profiles[::2]
    right = profiles[1::2]
    safe_cwd   = str(_GITHUB_DIR).replace("'", "'\\''")
    welcome    = str(fob_dir / "tools" / "welcome.sh").replace("'", "'\\''")
    claude_cmd = get_claude_command(profiles[0], Path(profiles[0]["repo_root"]))
    i = indent

    # Width: left/right each 28%, center gets the rest (~44% for 2 repos)
    side_pct = "28%"

    left_block = (
        f'{i}    pane size="{side_pct}" stacked=true {{\n'
        + _repo_stack_panes(left, indent=i + "        ")
        + f'{i}    }}\n'
    )

    center_block = (
        f'{i}    pane split_direction="horizontal" {{\n'
        f'{i}        pane name="claude" command="bash" {{\n'
        f'{i}            args "-c" "cd \'{safe_cwd}\' && {claude_cmd}"\n'
        f'{i}        }}\n'
        f'{i}        pane size="15%" name="shell" command="bash" {{\n'
        f'{i}            args "-c" "cd \'{safe_cwd}\' && bash \'{welcome}\'"\n'
        f'{i}        }}\n'
        f'{i}    }}\n'
    )

    right_block = (
        f'{i}    pane size="{side_pct}" stacked=true {{\n'
        + _repo_stack_panes(right, indent=i + "        ")
        + f'{i}    }}\n'
    ) if right else ""

    return (
        f'{i}pane split_direction="vertical" {{\n'
        + left_block
        + center_block
        + right_block
        + f'{i}}}'
    )


def _multi_tab_name(profiles: list[dict]) -> str:
    names = [p["name"] for p in profiles]
    if len(names) <= 3:
        return "+".join(names)
    return "+".join(names[:2]) + f"+{len(names) - 2}more"


# ── chrome / chrome-less wrappers ─────────────────────────────────────────────

def _chrome_template() -> str:
    return (
        '    default_tab_template {\n'
        '        pane size=1 borderless=true {\n'
        '            plugin location="tab-bar"\n'
        '        }\n'
        '        children\n'
        '        pane size=2 borderless=true {\n'
        '            plugin location="status-bar"\n'
        '        }\n'
        '    }\n'
    )


def _tab_chrome_wrap(panes_kdl: str) -> str:
    """Wrap pane KDL in a standalone tab layout with explicit chrome."""
    return (
        'layout {\n'
        '    pane size=1 borderless=true {\n'
        '        plugin location="tab-bar"\n'
        '    }\n'
        f'{panes_kdl}\n'
        '    pane size=2 borderless=true {\n'
        '        plugin location="status-bar"\n'
        '    }\n'
        '}\n'
    )


# ── public generators ─────────────────────────────────────────────────────────

def generate_session_kdl(profiles: list[dict], fob_dir: Path) -> str:
    """Return session layout KDL string (no side effects)."""
    if len(profiles) == 1:
        tab_name = profiles[0]["name"]
        panes    = _single_pane_block(profiles[0], fob_dir, indent="        ")
    else:
        tab_name = _multi_tab_name(profiles)
        panes    = _multi_pane_block(profiles, fob_dir, indent="        ")

    return (
        'layout {\n'
        + _chrome_template()
        + f'    tab name="{tab_name}" {{\n'
        + f'{panes}\n'
        + '    }\n'
        + '}\n'
    )


def generate_session_layout(profiles: list[dict], fob_dir: Path) -> Path:
    """Write session layout to /tmp, return path."""
    tmp = Path(tempfile.gettempdir()) / "fob-session.kdl"
    tmp.write_text(generate_session_kdl(profiles, fob_dir))
    return tmp


def generate_tab_layout(profiles: list[dict], fob_dir: Path) -> Path:
    """Write a standalone tab layout (for adding to running session) to /tmp."""
    if len(profiles) == 1:
        name  = profiles[0]["name"]
        panes = _single_pane_block(profiles[0], fob_dir, indent="    ")
    else:
        name  = _multi_tab_name(profiles)
        panes = _multi_pane_block(profiles, fob_dir, indent="    ")

    tmp = Path(tempfile.gettempdir()) / f"fob-tab-{name}.kdl"
    tmp.write_text(_tab_chrome_wrap(panes))
    return tmp, name


# ── session helpers ───────────────────────────────────────────────────────────

def _delete_dead_session(session_name: str) -> None:
    try:
        r = subprocess.run(["zellij", "list-sessions"], capture_output=True, text=True)
        import re
        ansi = re.compile(r"\033\[[0-9;]*m")
        for line in r.stdout.splitlines():
            clean = ansi.sub("", line).strip()
            parts = clean.split()
            if parts and parts[0] == session_name and "EXITED" in clean:
                subprocess.run(["zellij", "delete-session", session_name], capture_output=True)
                break
    except Exception:
        pass


def _list_tabs(session_name: str) -> set[str]:
    try:
        r = subprocess.run(
            ["zellij", "--session", session_name, "action", "query-tab-names"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return {line.strip() for line in r.stdout.splitlines() if line.strip()}
    except Exception:
        pass
    return set()


def attach(session_name: str = FOB_SESSION) -> None:
    os.execvp("zellij", ["zellij", "attach", session_name])


# ── launch ────────────────────────────────────────────────────────────────────

def launch(
    profiles: list[dict],
    fob_dir: Path,
    reset_layout: bool = False,
    saved_layout_path: Path | None = None,
) -> None:
    for profile in profiles:
        check_branch(Path(profile["repo_root"]))

    _delete_dead_session(FOB_SESSION)

    already_in_session = os.environ.get("ZELLIJ_SESSION_NAME") == FOB_SESSION
    if already_in_session or session_exists(FOB_SESSION):
        existing_tabs = _list_tabs(FOB_SESSION)
        layout_path, tab_name = generate_tab_layout(profiles, fob_dir)
        if tab_name in existing_tabs:
            print(f"  {_c('tab', 'DIM')}  {_c(tab_name, 'DIM')}  {_c('already open', 'DIM')}")
        else:
            subprocess.run([
                "zellij", "--session", FOB_SESSION,
                "action", "new-tab",
                "--name", tab_name,
                "--layout", str(layout_path),
            ])
            print(f"  {_c('tab', 'DIM')}  {_c(tab_name, 'GRN')}  {_c('added', 'GRN')}")
        if not os.environ.get("ZELLIJ"):
            attach(FOB_SESSION)
    else:
        if saved_layout_path is not None:
            layout_path = saved_layout_path
        else:
            layout_path = generate_session_layout(profiles, fob_dir)
        os.execvp(
            "zellij",
            ["zellij", "--session", FOB_SESSION, "--new-session-with-layout", str(layout_path)],
        )
