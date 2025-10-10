"""Command-line interface for the ``zotero-pdf2md`` package."""

from __future__ import annotations

import logging
from typing import Optional

import typer

from .exporter import export_library
from .settings import ExportSettings, LibraryType
from .utils import get_logger

app = typer.Typer(
    add_completion=False,
    help="Export PDF attachments from a Zotero library to Markdown files using the Web API.",
)

LOG_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def _configure_logging(level: str) -> None:
    logger = get_logger()
    logger.setLevel(LOG_LEVELS[level])


def _parse_key_value_option(value: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in value:
        if "=" not in item:
            raise typer.BadParameter("Options must be specified as key=value pairs.")
        key, val = item.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            raise typer.BadParameter("Option keys cannot be empty.")
        result[key] = val
    return result


@app.command("export")
def export_command(
    output_dir: str = typer.Argument(
        ...,
        help="Directory where Markdown files will be written.",
    ),
    api_key: str = typer.Option(
        ...,
        "--api-key",
        envvar="ZOTERO_API_KEY",
        prompt=True,
        hide_input=True,
        help="Zotero API key with read access to the target library.",
    ),
    library_id: str = typer.Option(
        ...,
        "--library-id",
        envvar="ZOTERO_LIBRARY_ID",
        prompt=True,
        help="Target Zotero library ID (numeric for user/group libraries).",
    ),
    library_type: LibraryType = typer.Option(
        "user",
        "--library-type",
        case_sensitive=False,
        help="Zotero library type: 'user' or 'group'.",
    ),
    collection: tuple[str, ...] = typer.Option(
        (),
        "--collection",
        "-c",
        help="Filter by collection key (multiple allowed).",
    ),
    tag: tuple[str, ...] = typer.Option(
        (),
        "--tag",
        "-t",
        help="Filter by tag name (multiple allowed).",
    ),
    limit: Optional[int] = typer.Option(
        None,
        help="Limit the number of attachments to export.",
    ),
    chunk_size: int = typer.Option(
        100,
        "--chunk-size",
        help="Number of attachments to fetch per API request (default 100).",
    ),
    max_workers: Optional[int] = typer.Option(
        None,
        "--max-workers",
        help="Upper bound on parallel download workers (default auto).",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing Markdown files instead of skipping.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="List target files without writing Markdown output or downloading attachments.",
    ),
    markdown_option: tuple[str, ...] = typer.Option(
        (),
        "--option",
        "-o",
        help="Additional pymupdf4llm.to_markdown options as key=value pairs.",
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        case_sensitive=False,
        help="Logging verbosity (critical, error, warning, info, debug).",
    ),
) -> None:
    """Export PDF attachments managed by a Zotero library via the Web API."""
    level = log_level.lower()
    if level not in LOG_LEVELS:
        raise typer.BadParameter(f"Invalid log level: {log_level}")
    _configure_logging(level)

    try:
        settings = ExportSettings.from_cli_args(
            api_key=api_key,
            library_id=library_id,
            library_type=library_type.lower(),  # type: ignore[arg-type]
            output_dir=output_dir,
            collections=collection,
            tags=tag,
            overwrite=overwrite,
            dry_run=dry_run,
            limit=limit,
            chunk_size=chunk_size,
            max_workers=max_workers,
            markdown_options=_parse_key_value_option(markdown_option),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    summary = export_library(settings)

    typer.echo("")
    typer.echo("Export summary:")
    typer.echo(f"  Processed attachments: {summary.processed}")
    typer.echo(f"  Converted:            {summary.converted}")
    typer.echo(f"  Skipped:              {summary.skipped}")
    typer.echo(f"  Dry-run:              {summary.dry_run}")

    if summary.output_paths:
        typer.echo("\nOutput files:")
        for path in summary.output_paths:
            typer.echo(f"  {path}")


def main() -> None:
    """Entry point for console scripts."""
    app()


if __name__ == "__main__":
    main()
