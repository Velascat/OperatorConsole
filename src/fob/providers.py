"""fob providers — open 9router dashboard and guide provider setup."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import webbrowser

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


# (name, models, sign-up method, note)
_PROVIDERS = [
    ("Kiro",   "Claude Sonnet 4.5",       "GitHub OAuth",   "recommended — fast, no quota"),
    ("iFlow",  "Deepseek R1, Qwen3, GLM", "OAuth",          ""),
    ("Qwen",   "Qwen3-Coder",             "device code",    ""),
    ("Gemini", "Gemini 2.5 Pro",          "Google OAuth",   "quota-limited"),
    ("Ollama", "any local model",         "no account",     "runs on your hardware; CPU-only is slow"),
]


def print_provider_table() -> None:
    print()
    print(f"  {_c('Free providers — no API key required:', 'B')}")
    print()
    print(f"  {_c('Provider', 'DIM'):<21}  {_c('Models', 'DIM'):<40}  {_c('Sign-up', 'DIM')}")
    print(f"  {_c('─' * 78, 'DIM')}")
    for name, models, auth, note in _PROVIDERS:
        note_str = f"   {_c(note, 'DIM')}" if note else ""
        print(f"  {_c(name, 'B'):<12}  {models:<36}  {auth}{note_str}")
    print()


def _active_providers(nr_port: str) -> list[dict]:
    try:
        req = urllib.request.Request(f"http://localhost:{nr_port}/api/providers")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
            providers = body if isinstance(body, list) else body.get("providers", [])
            return [p for p in providers if p.get("enabled") or p.get("active") or p.get("connected")]
    except Exception:
        return []


def run_providers(args: list[str]) -> int:
    do_wait  = "--wait" in args
    nr_port  = os.environ.get("PORT_9ROUTER", "20128")
    dashboard = f"http://localhost:{nr_port}"

    print(_c("\n  fob providers", "B", "CYN") + _c(" — connect a provider to 9router", "DIM"))
    _section("Stack")

    # Check 9router is reachable
    try:
        req = urllib.request.Request(f"{dashboard}/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            stack_ok = resp.status == 200
    except Exception:
        stack_ok = False

    if not stack_ok:
        _fail(f"9router not reachable at {dashboard}")
        _info("Start the stack first with:  fob demo")
        return 1

    _ok(f"9router running at {dashboard}")

    _section("Connected Providers")

    active = _active_providers(nr_port)
    if active:
        names = [p.get("name", p.get("id", "?")) for p in active]
        for name in names:
            _ok(name)
        print()
        _info("To add more providers, connect them in the dashboard.")
    else:
        _fail("No providers connected yet")

    print_provider_table()

    print(f"  {_c('Recommended:', 'B')} Kiro — free Claude Sonnet 4.5, GitHub OAuth, 30-second setup")
    print()

    # Open browser
    _section("Dashboard")
    _info(f"Opening {dashboard} ...")
    try:
        webbrowser.open(dashboard)
        _ok("Browser opened — connect a provider, then come back here")
    except Exception:
        _info(f"Could not open browser automatically")
        _info(f"Visit: {dashboard}")

    if do_wait:
        _section("Waiting")
        _info("Polling for a connected provider... (Ctrl+C to stop)")
        print()
        try:
            while True:
                time.sleep(3)
                providers = _active_providers(nr_port)
                if providers:
                    names = [p.get("name", p.get("id", "?")) for p in providers]
                    _ok(f"Provider connected: {', '.join(names)}")
                    print()
                    _info("Run:  fob demo --no-start  to validate the full platform")
                    return 0
                print(".", end="", flush=True)
        except KeyboardInterrupt:
            print()
            print()
            _info("Stopped. Run  fob demo  once you've connected a provider.")
            return 0
    else:
        print()
        _info("Once connected, run:")
        print(f"    {_c('fob demo --no-start', 'B')}   — validate the full platform")
        print()
        _info("Or use  --wait  to have this command poll until a provider appears:")
        print(f"    {_c('fob providers --wait', 'B')}")
        print()

    return 0
