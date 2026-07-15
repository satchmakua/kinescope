"""The Kinescope timeline TUI (DESIGN.md §7) — a three-pane Textual app.

  STEPS (left)         the event log; fork points / divergences marked
  DETAIL (top-right)   the selected step's input / output / meta
  DIFF (bottom-right)  the state delta vs. the previous snapshot

Scrub with ↑/↓, fork the highlighted step with `f`, quit with `q`. Launched view-only
via `kinescope ui <run-id>`; pass an `agent` callable (e.g. `kinescope.ui(run_id, agent=...)`)
to make `f` actually fork-and-run the counterfactual live.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Static

from ..diff import json_diff
from ..model import Event
from ..store.base import TraceStore

_KIND_STYLE = {
    "llm": "cyan",
    "tool": "green",
    "clock": "yellow",
    "rng": "magenta",
    "retrieval": "blue",
}


class ForkScreen(ModalScreen):
    """Collects an override JSON for a fork at a given step."""

    BINDINGS = [Binding("escape", "cancel", "cancel")]

    def __init__(self, seq: int, default_override: dict[str, Any] | None) -> None:
        super().__init__()
        self.seq = seq
        self._prefill = json.dumps(default_override or {"output": None})

    def compose(self) -> ComposeResult:
        with Vertical(id="fork-box"):
            yield Static(f"Fork at step {self.seq} — enter override JSON, then Enter:")
            yield Input(value=self._prefill, id="fork-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            override = json.loads(event.value)
        except json.JSONDecodeError:
            self.notify("invalid JSON", severity="error")
            return
        if "output" not in override:
            self.notify("override must include an 'output' key", severity="error")
            return
        self.dismiss((self.seq, override))

    def action_cancel(self) -> None:
        self.dismiss(None)


class KinescopeApp(App):
    """Scrub a recorded run; fork-and-fix the highlighted step."""

    CSS = """
    #steps { width: 40; border-right: solid $panel; }
    #detail-wrap { height: 2fr; border-bottom: solid $panel; }
    #diff-wrap { height: 1fr; }
    Static { padding: 0 1; }
    ForkScreen { align: center middle; }
    #fork-box {
        width: 70; height: auto; border: thick $accent; background: $surface; padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "quit"),
        Binding("f", "fork", "fork"),
        Binding("r", "reload", "reload"),
    ]

    def __init__(
        self,
        run_id: str,
        store: TraceStore,
        agent: Callable[[], Any] | None = None,
        default_override: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.run_id = run_id
        self.store = store
        self.agent = agent
        self.default_override = default_override
        self.events: list[Event] = []
        self.diverged_seqs: set[int] = set()
        self.last_detail = Text()  # exposed for tests / introspection
        self.last_diff = Text()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield DataTable(id="steps", cursor_type="row", zebra_stripes=True)
            with Vertical():
                yield VerticalScroll(Static(id="detail"), id="detail-wrap")
                yield VerticalScroll(Static(id="diff"), id="diff-wrap")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#steps", DataTable)
        table.add_columns("seq", "kind", "name", "")
        self.load_run(self.run_id)
        table.focus()

    # --- data loading --------------------------------------------------------

    def load_run(self, run_id: str) -> None:
        self.run_id = run_id
        run = self.store.get_run(run_id)
        self.events = self.store.events(run_id)
        self.diverged_seqs = {d["seq"] for d in run.divergences}
        self.title = "Kinescope"
        lineage = f"  ⑂ from {run.parent_run_id}@{run.forked_at_seq}" if run.parent_run_id else ""
        self.sub_title = f"{run.label}  {run_id}  ({run.status}){lineage}"

        table = self.query_one("#steps", DataTable)
        table.clear()
        for ev in self.events:
            if ev.meta.get("overridden"):
                marker = "fork"
            elif ev.seq in self.diverged_seqs:
                marker = "!"
            else:
                marker = ""
            kind = Text(ev.kind, style=_KIND_STYLE.get(ev.kind, ""))
            table.add_row(str(ev.seq), kind, ev.name, Text(marker, style="bold red"))
        if self.events:
            table.move_cursor(row=0)
        self.update_panes()

    # --- panes ---------------------------------------------------------------

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.update_panes()

    def update_panes(self) -> None:
        detail = self.query_one("#detail", Static)
        diff = self.query_one("#diff", Static)
        if not self.events:
            self.last_detail, self.last_diff = Text("(no events)", style="dim"), Text("")
            detail.update(self.last_detail)
            diff.update(self.last_diff)
            return
        row = self.query_one("#steps", DataTable).cursor_row
        ev = self.events[max(0, min(row, len(self.events) - 1))]
        self.last_detail = self._event_detail(ev)
        self.last_diff = self._diff_text(ev.seq)
        detail.update(self.last_detail)
        diff.update(self.last_diff)

    def _blob_text(self, blob_id: str, limit: int = 1200) -> str:
        raw = self.store.get_blob(blob_id)
        try:
            text = json.dumps(json.loads(raw), indent=2)
        except ValueError:
            text = raw.decode("utf-8", "replace")
        return text[:limit] + ("\n…(truncated)" if len(text) > limit else "")

    def _event_detail(self, ev: Event) -> Text:
        t = Text()
        t.append(f"#{ev.seq} ", style="bold")
        t.append(f"{ev.kind} ", style=_KIND_STYLE.get(ev.kind, ""))
        t.append(f"{ev.name}\n", style="bold")
        flags = "  overridden" if ev.meta.get("overridden") else ""
        t.append(f"{ev.status} · {ev.dur_ms:.0f}ms{flags}\n\n", style="dim")
        if ev.input_ref:
            t.append("input\n", style="bold")
            t.append(self._blob_text(ev.input_ref) + "\n\n")
        if ev.output_ref:
            t.append("output\n", style="bold")
            t.append(self._blob_text(ev.output_ref) + "\n\n")
        elif "value" in ev.meta:
            t.append("value\n", style="bold")
            t.append(f"{ev.meta['value']}\n\n")
        slim = {k: v for k, v in ev.meta.items() if k not in ("resp_headers", "value")}
        if slim:
            t.append("meta\n", style="bold")
            t.append(json.dumps(slim, indent=2))
        return t

    def _diff_text(self, seq: int) -> Text:
        snaps = self.store.snapshots(self.run_id)
        if not snaps:
            return Text("(no snapshots — call kinescope.snapshot(state) in the agent)", style="dim")
        before = [s for s in snaps if s.after_seq <= seq]
        cur = before[-1] if before else snaps[0]
        idx = snaps.index(cur)
        prev = snaps[idx - 1] if idx > 0 else None
        cur_state = json.loads(self.store.get_blob(cur.state_ref))
        prev_state = json.loads(self.store.get_blob(prev.state_ref)) if prev else {}
        ops = json_diff(prev_state, cur_state)
        head = Text(f"state diff  ({prev.label if prev else 'init'} → {cur.label})\n", style="dim")
        if not ops:
            return head + Text("(no change)", style="dim")
        body = Text()
        sign = {"add": ("+", "green"), "remove": ("-", "red"), "replace": ("~", "yellow")}
        for op in ops:
            glyph, style = sign[op["op"]]
            body.append(f"{glyph} {op['path']}", style=style)
            if op["op"] != "remove":
                body.append(f"  {json.dumps(op['value'])}", style="dim")
            body.append("\n")
        return head + body

    # --- actions -------------------------------------------------------------

    def action_reload(self) -> None:
        self.load_run(self.run_id)

    def action_fork(self) -> None:
        if self.agent is None:
            self.notify(
                "fork needs an agent — launch via kinescope.ui(run_id, agent=...)",
                severity="warning",
            )
            return
        seq = self.query_one("#steps", DataTable).cursor_row
        self.push_screen(ForkScreen(seq, self.default_override), self._fork_submitted)

    def _fork_submitted(self, result: tuple[int, dict[str, Any]] | None) -> None:
        if result is not None:
            self.do_fork(*result)

    def do_fork(self, at: int, override: dict[str, Any]) -> str:
        """Fork at `at`, run the agent live for the tail, and switch to the new child run."""
        from ..branch import fork

        with fork(self.run_id, at, override, self.store) as branch:
            assert self.agent is not None
            self.agent()
        child_id = branch.run_id
        self.notify(f"forked at {at} → {child_id}")
        self.load_run(child_id)
        return child_id


def run_tui(
    run_id: str,
    store: TraceStore | None = None,
    agent: Callable[[], Any] | None = None,
    default_override: dict[str, Any] | None = None,
) -> None:
    from ..store.local import LocalStore

    store = store or LocalStore()
    KinescopeApp(run_id, store, agent=agent, default_override=default_override).run()
