"""An agent entry point for the CLI runner (offline — no network, no key).

It does NOT open its own `eidetic.record()` — the CLI provides the session:

    eidetic record -- python examples/agent_script.py
    eidetic replay <run-id> -- python examples/agent_script.py
    eidetic fork <run-id> --at 0 --override '{"output": 6}' -- python examples/agent_script.py

Its only Eidetic touch-point is decorating tools with `@eidetic.tool` (a real agent would also
build its LLM client with `eidetic.http_client()`).
"""

from __future__ import annotations

import random

import eidetic


@eidetic.tool
def roll(sides: int = 6) -> int:
    return random.randint(1, sides)


def main() -> None:
    rolls = [roll() for _ in range(3)]
    print(f"rolls: {rolls}  sum: {sum(rolls)}")


if __name__ == "__main__":
    main()
