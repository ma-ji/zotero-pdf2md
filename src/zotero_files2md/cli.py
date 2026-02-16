"""Command-line interface for the ``zotero-files2md`` package."""

from __future__ import annotations

import logging
from typing import List, Optional

import typer

from .settings import (
    ExportSettings,
    LibraryType,
    ReferenceFolderName,
    parse_collection_output_pairs,
)
from .utils import get_logger

app = typer.Typer(
    add_completion=False,
    help=(
        "Export file attachments from a Zotero library to Markdown files "
        "using Docling and the Zotero Web API."
    ),
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
    collection: List[str] = typer.Option(
        None,
        "--collection",
        "-c",
        help="Filter by collection key (multiple allowed).",
    ),
    tag: List[str] = typer.Option(
        None,
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
        help=(
            "Upper bound on parallel download/conversion workers (default auto). "
            "In multi-GPU mode, total workers are additionally capped by "
            "GPU_count * --workers-per-gpu."
        ),
    ),
    workers_per_gpu: int = typer.Option(
        1,
        "--workers-per-gpu",
        help="Maximum worker processes per GPU in multi-GPU mode (lower to reduce OOM risk).",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing Markdown files instead of skipping.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "List target files without downloading attachments or "
            "writing Markdown output."
        ),
    ),
    force_full_page_ocr: bool = typer.Option(
        False,
        "--force-full-page-ocr",
        help="Force full-page OCR for better quality (slower).",
    ),
    do_picture_description: bool = typer.Option(
        False,
        "--do-picture-description",
        help="Enable GenAI picture description (slower).",
    ),
    image_resolution_scale: float = typer.Option(
        4.0,
        "--image-resolution-scale",
        help="Image resolution scale for Docling.",
    ),
    image_processing: str = typer.Option(
        "embed",
        "--image-processing",
        case_sensitive=False,
        help="How to handle images in Markdown output (embed, placeholder, drop).",
    ),
    reference_folder_name: ReferenceFolderName = typer.Option(
        "citation-key",
        "--reference-folder-name",
        case_sensitive=False,
        help=(
            "How to name each reference folder "
            "('citation-key' or 'item-title')."
        ),
    ),
    use_multi_gpu: bool = typer.Option(
        True,
        "--use-multi-gpu/--no-use-multi-gpu",
        help="Distribute processing across available GPUs.",
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        case_sensitive=False,
        help="Logging verbosity (critical, error, warning, info, debug).",
    ),
) -> None:
    """Export file attachments managed by a Zotero library via the Web API."""
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
            workers_per_gpu=workers_per_gpu,
            force_full_page_ocr=force_full_page_ocr,
            do_picture_description=do_picture_description,
            image_resolution_scale=image_resolution_scale,
            image_processing=image_processing,
            use_multi_gpu=use_multi_gpu,
            reference_folder_name=reference_folder_name,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    from .exporter import export_library

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


@app.command("export-batch")
def export_batch_command(
    collection_output: List[str] = typer.Option(
        ...,
        "--collection-output",
        "-C",
        help="Export a collection to a specific output directory (repeatable): COLLECTION_KEY=OUTPUT_DIR.",
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
    tag: List[str] = typer.Option(
        None,
        "--tag",
        "-t",
        help="Filter by tag name (multiple allowed).",
    ),
    limit: Optional[int] = typer.Option(
        None,
        help="Limit the number of attachments to export (applies per collection).",
    ),
    chunk_size: int = typer.Option(
        100,
        "--chunk-size",
        help="Number of attachments to fetch per API request (default 100).",
    ),
    max_workers: Optional[int] = typer.Option(
        None,
        "--max-workers",
        help=(
            "Upper bound on parallel download/conversion workers (default auto). "
            "In multi-GPU mode, total workers are additionally capped by "
            "GPU_count * --workers-per-gpu."
        ),
    ),
    workers_per_gpu: int = typer.Option(
        1,
        "--workers-per-gpu",
        help="Maximum worker processes per GPU in multi-GPU mode (lower to reduce OOM risk).",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing Markdown files instead of skipping.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "List target files without downloading attachments or "
            "writing Markdown output."
        ),
    ),
    force_full_page_ocr: bool = typer.Option(
        False,
        "--force-full-page-ocr",
        help="Force full-page OCR for better quality (slower).",
    ),
    do_picture_description: bool = typer.Option(
        False,
        "--do-picture-description",
        help="Enable GenAI picture description (slower).",
    ),
    image_resolution_scale: float = typer.Option(
        4.0,
        "--image-resolution-scale",
        help="Image resolution scale for Docling.",
    ),
    image_processing: str = typer.Option(
        "embed",
        "--image-processing",
        case_sensitive=False,
        help="How to handle images in Markdown output (embed, placeholder, drop).",
    ),
    reference_folder_name: ReferenceFolderName = typer.Option(
        "citation-key",
        "--reference-folder-name",
        case_sensitive=False,
        help=(
            "How to name each reference folder "
            "('citation-key' or 'item-title')."
        ),
    ),
    use_multi_gpu: bool = typer.Option(
        True,
        "--use-multi-gpu/--no-use-multi-gpu",
        help="Distribute processing across available GPUs.",
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        case_sensitive=False,
        help="Logging verbosity (critical, error, warning, info, debug).",
    ),
) -> None:
    """Export multiple collections to different output directories in one run."""
    level = log_level.lower()
    if level not in LOG_LEVELS:
        raise typer.BadParameter(f"Invalid log level: {log_level}")
    _configure_logging(level)

    try:
        collection_output_dirs = parse_collection_output_pairs(collection_output)
        if not collection_output_dirs:
            raise ValueError("At least one --collection-output must be provided.")

        first_output_dir = next(iter(collection_output_dirs.values()))
        base_settings = ExportSettings.from_cli_args(
            api_key=api_key,
            library_id=library_id,
            library_type=library_type.lower(),  # type: ignore[arg-type]
            output_dir=first_output_dir,
            collections=[],
            tags=tag,
            overwrite=overwrite,
            dry_run=dry_run,
            limit=limit,
            chunk_size=chunk_size,
            max_workers=max_workers,
            workers_per_gpu=workers_per_gpu,
            force_full_page_ocr=force_full_page_ocr,
            do_picture_description=do_picture_description,
            image_resolution_scale=image_resolution_scale,
            image_processing=image_processing,
            use_multi_gpu=use_multi_gpu,
            reference_folder_name=reference_folder_name,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    from .exporter import export_collections

    batch_summary = export_collections(base_settings, collection_output_dirs)

    typer.echo("")
    typer.echo("Batch export summary:")
    typer.echo(f"  Runs:                 {len(batch_summary.runs)}")
    typer.echo(f"  Processed attachments: {batch_summary.processed}")
    typer.echo(f"  Converted:            {batch_summary.converted}")
    typer.echo(f"  Skipped:              {batch_summary.skipped}")
    typer.echo(f"  Dry-run:              {batch_summary.dry_run}")

    for run in batch_summary.runs:
        typer.echo("")
        typer.echo(f"Collection {run.collection_key} -> {run.output_dir}")
        typer.echo(f"  Processed attachments: {run.summary.processed}")
        typer.echo(f"  Converted:            {run.summary.converted}")
        typer.echo(f"  Skipped:              {run.summary.skipped}")
        typer.echo(f"  Dry-run:              {run.summary.dry_run}")


def main() -> None:
    """Entry point for console scripts."""
    app()


if __name__ == "__main__":
    main()
