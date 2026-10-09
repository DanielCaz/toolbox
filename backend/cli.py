"""Toolbox CLI: the same registry and params as the web UI.

uv run python cli.py list
uv run python cli.py info pdf.split
uv run python cli.py run pdf.merge a.pdf b.pdf -p output_name=both.pdf -o out/
uv run python cli.py pipeline my-preset-or-file.json scan1.pdf scan2.pdf -o out/
uv run python cli.py watch ~/inbox            # folders named after saved pipelines
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import typer

from app.config import get_settings
from app.core.errors import ApiError, ToolError
from app.core.files import check_inputs
from app.core.jobs import execute, validate_params
from app.core.pipelines import PipelineDef, PipelineStore, run_pipeline, validate_pipeline
from app.core.registry import Registry
from app.core.tool import ToolContext
from app.core.watch import Watcher

app = typer.Typer(help="Everyday file tools from the terminal.", no_args_is_help=True)


def _registry() -> Registry:
    return Registry()


def _parse_param(item: str) -> tuple[str, object]:
    key, sep, raw = item.partition("=")
    if not sep or not key:
        raise typer.BadParameter(f"'{item}' is not in key=value form")
    try:
        return key, json.loads(raw)  # numbers, true/false, null, "quoted"
    except json.JSONDecodeError:
        return key, raw  # plain strings stay strings


@app.command("list")
def list_tools():
    """List all tools."""
    reg = _registry()
    last_category = None
    for entry in reg.catalog():
        if entry["category"] != last_category:
            typer.secho(f"\n{entry['category'].upper()}", bold=True)
            last_category = entry["category"]
        flag = "" if entry["available"] else f"  (missing: {', '.join(entry['missing'])})"
        typer.echo(f"  {entry['id']:<22} {entry['description']}{flag}")


@app.command()
def info(tool_id: str):
    """Show a tool's accepted files and parameters."""
    reg = _registry()
    try:
        entry = reg.describe(reg.get(tool_id))
    except ApiError as e:
        typer.secho(e.message, fg="red", err=True)
        raise typer.Exit(1) from None
    typer.secho(f"{entry['name']} ({entry['id']})", bold=True)
    typer.echo(entry["description"])
    typer.echo(
        f"Accepts: {', '.join(entry['accepts']) or 'any'}  |  files: "
        f"{entry['min_files']}..{entry['max_files'] or 'many'}  |  output: {entry['output']}"
    )
    props = entry["schema"].get("properties", {})
    if props:
        typer.echo("\nParameters (-p key=value):")
        for key, spec in props.items():
            typer.echo(
                f"  {key:<14} default={spec.get('default')!r}  {spec.get('description', '')}"
            )


@app.command()
def run(
    tool_id: str,
    files: list[Path] = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    param: list[str] = typer.Option([], "--param", "-p", help="key=value, repeatable"),
    out: Path = typer.Option(Path("out"), "--out", "-o", help="Output folder"),
):
    """Run a tool on one or more files."""
    reg = _registry()
    try:
        tool = reg.get(tool_id)
        missing = reg.missing(tool)
        if missing:
            raise ApiError(503, "tool_unavailable", f"Missing binaries: {', '.join(missing)}")
        check_inputs(tool, files)
        params = validate_params(tool, dict(_parse_param(p) for p in param))
    except ApiError as e:
        typer.secho(e.message, fg="red", err=True)
        if e.detail:
            typer.echo(json.dumps(e.detail, indent=2), err=True)
        raise typer.Exit(2) from None

    def progress(fraction: float, message: str) -> None:
        typer.echo(f"[{fraction:>4.0%}] {message}", err=True)

    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="toolbox-") as tmp:
        try:
            result = execute(tool, files, params, Path(tmp), progress)
        except ToolError as e:
            typer.secho(f"Error: {e}", fg="red", err=True)
            raise typer.Exit(1) from None

        if tool.output == "text":
            sys.stdout.write((result.text or "") + "\n")
            return
        for p in result.outputs:
            dest = out / p.name
            n = 1
            while dest.exists():
                dest = out / f"{p.stem}-{n}{p.suffix}"
                n += 1
            shutil.copy2(p, dest)
            typer.echo(str(dest))


def _copy_unique(src: Path, out: Path) -> Path:
    dest, n = out / src.name, 1
    while dest.exists():
        dest = out / f"{src.stem}-{n}{src.suffix}"
        n += 1
    shutil.copy2(src, dest)
    return dest


@app.command()
def pipeline(
    source: str = typer.Argument(..., help="A saved pipeline id, or a path to a pipeline .json"),
    files: list[Path] = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out: Path = typer.Option(Path("out"), "--out", "-o", help="Output folder"),
):
    """Run a saved or file-based pipeline (several tools chained) on files."""
    reg = _registry()
    try:
        path = Path(source)
        if path.suffix == ".json" and path.is_file():
            definition = PipelineDef.model_validate_json(path.read_text(encoding="utf-8"))
        else:
            definition = PipelineStore(get_settings().data_dir / "pipelines").get(source)
        validate_pipeline(reg, definition)
    except ApiError as e:
        typer.secho(e.message, fg="red", err=True)
        raise typer.Exit(2) from None
    except ValueError as e:
        typer.secho(f"Invalid pipeline file: {e}", fg="red", err=True)
        raise typer.Exit(2) from None

    def progress(fraction: float, message: str) -> None:
        typer.echo(f"[{fraction:>4.0%}] {message}", err=True)

    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="toolbox-") as tmp:
        ctx = ToolContext(workdir=Path(tmp), progress=progress)
        try:
            result = run_pipeline(reg, definition, list(files), ctx)
        except ToolError as e:
            typer.secho(f"Error: {e}", fg="red", err=True)
            raise typer.Exit(1) from None
        if result.text is not None:
            sys.stdout.write(result.text + "\n")
            return
        for p in result.outputs:
            typer.echo(str(_copy_unique(p, out)))


@app.command()
def watch(
    folder: Path = typer.Argument(..., file_okay=False, help="Folder holding <pipeline-id>/ dirs"),
    interval: float = typer.Option(2.0, help="Seconds between scans"),
    once: bool = typer.Option(False, "--once", help="Scan twice (so new files settle), then exit"),
):
    """Process files dropped into <folder>/<pipeline-id>/ (results go to _out/)."""
    import logging
    import time

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    watcher = Watcher(
        _registry(),
        PipelineStore(settings.data_dir / "pipelines"),
        folder,
        Path(tempfile.mkdtemp(prefix="toolbox-watch-")),
        interval,
    )
    if once:
        watcher.scan_once()
        watcher.scan_once()
        return
    typer.echo(f"Watching {folder} - Ctrl+C to stop", err=True)
    try:
        while True:
            watcher.scan_once()
            time.sleep(interval)
    except KeyboardInterrupt:
        watcher.stop()


if __name__ == "__main__":
    app()
