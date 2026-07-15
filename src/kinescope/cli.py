"""The `kinescope` CLI (DESIGN.md §6.7): `record`/`replay`/`fork` (run an agent script via
`-- python your_agent.py`), plus `ls`, `show`, `diff`, `ui`, `export`/`import`, and
`export-otel`.
"""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .branch import fork as _fork
from .diff import diff_snapshots
from .engine import record as _record
from .engine import replay as _replay
from .runner import run_script, split_command
from .store.local import LocalStore

app = typer.Typer(
    help="Kinescope — deterministic record-replay for AI agents.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


_PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


def _parse_capture(capture: str) -> Any:
    if not capture:
        return ()
    if capture == "all":
        return "all"
    return [c.strip() for c in capture.split(",") if c.strip()]


@app.command(context_settings=_PASSTHROUGH)
def record(
    ctx: typer.Context,
    label: str = typer.Option("run", help="Run label."),
    store: str = typer.Option(".kinescope", help="Trace store directory."),
    capture: str = typer.Option("", help="Stdlib capture: any of clock,rng,uuid or 'all'."),
) -> None:
    """Record an agent script: `kinescope record -- python your_agent.py [args]`.

    The script must build its client with `kinescope.http_client()` and must NOT call
    `kinescope.record()` itself (this command provides the session).
    """
    script, argv = split_command(ctx.args)
    with _record(label, LocalStore(store), capture=_parse_capture(capture)) as ses:
        run_script(script, argv)
    console.print(f"recorded run [bold]{ses.run_id}[/bold] ({len(ses.events)} events)")


@app.command(context_settings=_PASSTHROUGH)
def replay(
    ctx: typer.Context,
    run_id: str = typer.Argument(..., help="Run id to replay."),
    store: str = typer.Option(".kinescope", help="Trace store directory."),
    policy: str = typer.Option("warn", help="Divergence policy: strict | warn | off."),
) -> None:
    """Replay an agent script deterministically: `kinescope replay <id> -- python your_agent.py`."""
    script, argv = split_command(ctx.args)
    with _replay(run_id, LocalStore(store), policy=policy) as ses:  # type: ignore[arg-type]
        run_script(script, argv)
    if ses.divergences:
        console.print(f"[yellow](!) {len(ses.divergences)} divergence(s):[/yellow]")
        for d in ses.divergences:
            console.print(f"   seq {d['seq']}: {d['reason']}")
    else:
        console.print("[green]replayed with 0 divergences[/green]")


@app.command(context_settings=_PASSTHROUGH)
def fork(
    ctx: typer.Context,
    run_id: str = typer.Argument(..., help="Parent run id."),
    at: int = typer.Option(..., "--at", help="Step (seq) to fork at."),
    override: str = typer.Option(..., "--override", help='Override JSON, e.g. \'{"output": 72}\'.'),
    store: str = typer.Option(".kinescope", help="Trace store directory."),
) -> None:
    """Fork a run at a step, override that step's output, and run the tail live:
    `kinescope fork <id> --at 3 --override '{"output": 72}' -- python your_agent.py`."""
    try:
        override_obj = json.loads(override)
    except json.JSONDecodeError as exc:
        console.print(f"[red]--override must be valid JSON: {exc}[/red]")
        raise typer.Exit(1) from exc
    script, argv = split_command(ctx.args)
    with _fork(run_id, at, override_obj, LocalStore(store)) as ses:
        run_script(script, argv)
    console.print(f"forked run [bold]{ses.run_id}[/bold] (from {run_id} @ step {at})")


@app.command("ls")
def ls(store: str = typer.Option(".kinescope", help="Trace store directory.")) -> None:
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
    store: str = typer.Option(".kinescope", help="Trace store directory."),
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
    store: str = typer.Option(".kinescope", help="Trace store directory."),
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


@app.command("export")
def export_cmd(
    run_id: str,
    path: str = typer.Argument(..., help="Output bundle path (.zip)."),
    store: str = typer.Option(".kinescope", help="Trace store directory."),
) -> None:
    """Export a run to a portable, shareable bundle (events + snapshots + blobs)."""
    from .export.bundle import export_bundle

    out = export_bundle(run_id, path, LocalStore(store))
    console.print(f"wrote {out} ({out.stat().st_size:,} bytes)")


@app.command("import")
def import_cmd(
    path: str = typer.Argument(..., help="Bundle path to import."),
    store: str = typer.Option(".kinescope", help="Trace store directory."),
) -> None:
    """Import a trace bundle into the local store (replayable/forkable afterward)."""
    from .export.bundle import import_bundle

    run_id = import_bundle(path, LocalStore(store))
    console.print(f"imported run {run_id}")


@app.command("export-otel")
def export_otel_cmd(
    run_id: str,
    store: str = typer.Option(".kinescope", help="Trace store directory."),
) -> None:
    """Export a run as OpenTelemetry GenAI spans to the console (needs the 'otel' extra)."""
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        from .export.otel import export_otel
    except ModuleNotFoundError as exc:
        console.print("[red]Export needs the 'otel' extra:  pip install kinescope[otel][/red]")
        raise typer.Exit(1) from exc
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    n = export_otel(run_id, LocalStore(store), tracer_provider=provider)
    provider.force_flush()
    console.print(f"exported {n} gen_ai span(s) + 1 run span")


@app.command("ui")
def ui(
    run_id: str,
    store: str = typer.Option(".kinescope", help="Trace store directory."),
) -> None:
    """Open the timeline TUI to scrub a run (view-only; fork via kinescope.ui(..., agent=...))."""
    try:
        from .tui.app import run_tui
    except ModuleNotFoundError as exc:
        console.print("[red]The TUI needs the 'tui' extra:  pip install kinescope[tui][/red]")
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
