"""The `eidetic` CLI (DESIGN.md §6.7). M0 surface: `ls` and `show`.

`replay`/`fork`/`ui` arrive in later milestones once there's an agent entry point and
the TUI to drive them.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from .diff import diff_snapshots
from .store.local import LocalStore

app = typer.Typer(
    help="Eidetic — deterministic record-replay for AI agents.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command("ls")
def ls(store: str = typer.Option(".eidetic", help="Trace store directory.")) -> None:
    """List recorded runs."""
    s = LocalStore(store)
    runs = s.list_runs()
    if not runs:
        console.print(f"[dim]no runs in {store}/[/dim]")
        raise typer.Exit()
    table = Table(title=f"runs in {store}/")
    for col in ("run id", "label", "status", "events", "diverge", "forked from"):
        table.add_column(col)
    for r in runs:
        n_events = len(s.events(r.run_id))
        status_style = {"complete": "green", "diverged": "yellow", "error": "red"}.get(r.status, "")
        lineage = f"{r.parent_run_id}@{r.forked_at_seq}" if r.parent_run_id else "-"
        table.add_row(
            r.run_id,
            r.label,
            f"[{status_style}]{r.status}[/{status_style}]" if status_style else r.status,
            str(n_events),
            str(len(r.divergences)),
            lineage,
        )
    console.print(table)


@app.command("show")
def show(
    run_id: str,
    step: int | None = typer.Option(None, "--step", help="Show only this step (seq)."),
    store: str = typer.Option(".eidetic", help="Trace store directory."),
) -> None:
    """Show a run's events (and a preview of each call's I/O)."""
    s = LocalStore(store)
    run = s.get_run(run_id)
    events = s.events(run_id)
    console.print(f"[bold]{run.label}[/bold]  {run.run_id}  ({run.status})")
    if run.divergences:
        console.print(f"[yellow](!) {len(run.divergences)} divergence(s)[/yellow]")
    selected = [e for e in events if step is None or e.seq == step]
    for ev in selected:
        console.print(
            f"\n[cyan]#{ev.seq}[/cyan] {ev.kind} [bold]{ev.name}[/bold]  ({ev.dur_ms:.0f}ms)"
        )
        if ev.input_ref:
            console.print("  in :", _preview(s.get_blob(ev.input_ref)))
        if ev.output_ref:
            console.print("  out:", _preview(s.get_blob(ev.output_ref)))


@app.command("diff")
def diff(
    run_id: str,
    a: int = typer.Argument(..., help="From step (seq)."),
    b: int = typer.Argument(..., help="To step (seq)."),
    store: str = typer.Option(".eidetic", help="Trace store directory."),
) -> None:
    """Show the state diff between two steps (uses the nearest preceding snapshots)."""
    s = LocalStore(store)
    try:
        ops = diff_snapshots(s, run_id, a, b)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if not ops:
        console.print(f"[dim]no state change between step {a} and {b}[/dim]")
        return
    glyph = {"add": ("[green]", "+"), "remove": ("[red]", "-"), "replace": ("[yellow]", "~")}
    console.print(f"state diff  step {a} -> {b}")
    for op in ops:
        style, sign = glyph[op["op"]]
        val = "" if op["op"] == "remove" else f"  {json.dumps(op['value'])}"
        console.print(f"  {style}{sign} {op['path']}{val}[/]")


@app.command("export-otel")
def export_otel_cmd(
    run_id: str,
    store: str = typer.Option(".eidetic", help="Trace store directory."),
) -> None:
    """Export a run as OpenTelemetry GenAI spans to the console (needs the 'otel' extra)."""
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        from .export.otel import export_otel
    except ModuleNotFoundError as exc:
        console.print("[red]Export needs the 'otel' extra:  pip install eidetic[otel][/red]")
        raise typer.Exit(1) from exc
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    n = export_otel(run_id, LocalStore(store), tracer_provider=provider)
    provider.force_flush()
    console.print(f"exported {n} gen_ai span(s) + 1 run span")


@app.command("ui")
def ui(
    run_id: str,
    store: str = typer.Option(".eidetic", help="Trace store directory."),
) -> None:
    """Open the timeline TUI to scrub a run (view-only; fork via eidetic.ui(..., agent=...))."""
    try:
        from .tui.app import run_tui
    except ModuleNotFoundError as exc:
        console.print("[red]The TUI needs the 'tui' extra:  pip install eidetic[tui][/red]")
        raise typer.Exit(1) from exc
    run_tui(run_id, LocalStore(store))


def _preview(blob: bytes, limit: int = 240) -> str:
    try:
        text = json.dumps(json.loads(blob), separators=(",", ":"))
    except ValueError:
        text = blob.decode("utf-8", "replace")
    return text[:limit] + ("..." if len(text) > limit else "")


if __name__ == "__main__":
    app()
