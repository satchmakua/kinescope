"""The CLI entry-point runner: `eidetic record/replay/fork -- python agent.py` runs a user's
script in-process under a session so its boundaries are captured — turning the library into a
command-line tool."""

from __future__ import annotations

from typer.testing import CliRunner

import eidetic
from eidetic.cli import app
from eidetic.runner import run_script, split_command
from eidetic.store.local import LocalStore

AGENT = '''
import eidetic

@eidetic.tool
def add(a, b):
    return a + b

def main():
    print("RESULT", add(2, 3), add(4, 5))

if __name__ == "__main__":
    main()
'''


def _write_agent(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text(AGENT)
    return str(script)


def test_split_command_strips_interpreter():
    assert split_command(["python", "a.py", "--x"]) == ("a.py", ["--x"])
    assert split_command(["a.py", "1"]) == ("a.py", ["1"])


def test_run_script_records_then_replays(tmp_path):
    script = _write_agent(tmp_path)
    store = LocalStore(tmp_path / ".eidetic")

    with eidetic.record("r", store=store) as rec:
        run_script(script, [])
    assert len(store.events(rec.run_id)) == 2  # two @tool calls captured from the script

    with eidetic.replay(rec.run_id, store=store) as rep:
        run_script(script, [])
    assert rep.divergences == []


def test_cli_record_replay_roundtrip(tmp_path):
    script = _write_agent(tmp_path)
    store = str(tmp_path / ".eidetic")
    cli = CliRunner()

    rec = cli.invoke(app, ["record", "--store", store, "--", "python", script])
    assert rec.exit_code == 0, rec.output
    assert "recorded run" in rec.output

    run_id = LocalStore(store).list_runs()[0].run_id
    rep = cli.invoke(app, ["replay", run_id, "--store", store, "--", "python", script])
    assert rep.exit_code == 0, rep.output
    assert "0 divergences" in rep.output


def test_cli_fork_from_command_line(tmp_path):
    script = _write_agent(tmp_path)
    store = str(tmp_path / ".eidetic")
    cli = CliRunner()

    cli.invoke(app, ["record", "--store", store, "--", "python", script])
    parent = LocalStore(store).list_runs()[0].run_id

    # override add(2,3)=5 at seq 0 → 999; the second add re-runs live
    forked = cli.invoke(
        app,
        ["fork", parent, "--at", "0", "--override", '{"output": 999}', "--store", store,
         "--", "python", script],
    )
    assert forked.exit_code == 0, forked.output
    assert "forked run" in forked.output

    runs = {r.run_id: r for r in LocalStore(store).list_runs()}
    child = next(r for r in runs.values() if r.parent_run_id == parent)
    assert child.forked_at_seq == 0
