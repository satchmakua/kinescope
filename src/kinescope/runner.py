"""In-process agent runner for the CLI `record` / `replay` / `fork` commands.

`kinescope record -- python your_agent.py [args]` runs the script's `__main__` inside an active
Kinescope session, so its boundaries are captured. The contract: the script builds its LLM
client with `kinescope.http_client()` and does NOT open its own `kinescope.record()` (the runner
provides the session). Running in-process — not a subprocess — is what lets the session's
contextvar and transport reach the agent's calls.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_INTERPRETERS = {"python", "python3", "py", "python.exe", "py.exe"}


def split_command(cmd: list[str]) -> tuple[str, list[str]]:
    """Turn a token list like ``['python', 'agent.py', '--x']`` into ``('agent.py', ['--x'])``.

    A leading interpreter token is dropped; otherwise ``cmd[0]`` is taken as the script path.
    """
    if not cmd:
        raise ValueError(
            "no command given — usage: kinescope <cmd> [opts] -- python your_agent.py [args]"
        )
    tokens = list(cmd)
    if tokens[0].lower() in _INTERPRETERS:
        tokens = tokens[1:]
    if not tokens:
        raise ValueError("no script to run after the interpreter")
    return tokens[0], tokens[1:]


def run_script(script: str, argv: list[str]) -> None:
    """Execute ``script`` as ``__main__`` in-process, with ``argv`` as its ``sys.argv`` tail."""
    if not Path(script).exists():
        raise FileNotFoundError(f"no such script: {script}")
    saved = sys.argv
    sys.argv = [script, *argv]
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exc:  # a script calling sys.exit(0) is a normal finish
        if exc.code not in (0, None):
            raise
    finally:
        sys.argv = saved
