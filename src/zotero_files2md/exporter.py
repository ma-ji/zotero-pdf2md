"""High-level orchestration for exporting Zotero-managed attachments to Markdown."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

from .converter import ConversionResult, convert_attachment_to_markdown
from .models import AttachmentMetadata
from .settings import ExportSettings
from .utils import compute_output_path, get_logger
from .zotero import ZoteroClient

logger = get_logger()


@dataclass(slots=True, frozen=True)
class ExportSummary:
    """Summary of a full export run."""

    processed: int
    converted: int
    skipped: int
    dry_run: int
    output_paths: tuple[Path, ...]


def export_library(settings: ExportSettings) -> ExportSummary:
    """Export all matching Zotero attachments to Markdown via the Web API.

    All imported file attachments are considered; conversion is delegated to
    Docling, which may skip unsupported formats.
    """
    logger.info("Starting export via Zotero Web API")
    for line in settings.to_cli_summary():
        logger.info(line)

    results: list[ConversionResult] = []

    with TemporaryDirectory(prefix="zotero-files2md-") as tmp_dir:
        temp_dir = Path(tmp_dir)

        with ZoteroClient(settings) as client:
            # Fetch all imported attachments regardless of MIME type; Docling
            # will perform format-specific handling and may skip unsupported
            # files during conversion.
            attachments = list(client.iter_attachments())

        total_attachments = len(attachments)
        if total_attachments == 0:
            logger.info("No attachments matched the requested filters.")
            return summarize_results([])

        logger.info("Found %d attachment(s) to process.", total_attachments)

        if settings.dry_run:
            for attachment in attachments:
                file_path = _temp_path_for_attachment(temp_dir, attachment)
                results.append(
                    convert_attachment_to_markdown(attachment, file_path, settings)
                )
            return summarize_results(results)

        download_workers = settings.max_workers or min(8, total_attachments)
        download_workers = max(1, download_workers)
        conversion_futures: dict = {}

        # Pre-filter attachments when skip_existing is enabled
        attachments_to_process: list[AttachmentMetadata] = []
        seen_output_paths: set[Path] = set()

        for attachment in attachments:
            output_path = compute_output_path(attachment, settings.output_dir)

            if output_path in seen_output_paths:
                logger.info(
                    "Skipping duplicate output path for attachment %s: %s",
                    attachment.attachment_key,
                    output_path,
                )
                results.append(
                    ConversionResult(
                        source=Path(attachment.filename or attachment.attachment_key),
                        output=output_path,
                        status="skipped",
                    )
                )
                continue

            if settings.skip_existing:
                if output_path.exists():
                    logger.info(
                        "Skipping existing file (skip_existing): %s", output_path
                    )
                    results.append(
                        ConversionResult(
                            source=Path(
                                attachment.filename or attachment.attachment_key
                            ),
                            output=output_path,
                            status="skipped",
                        )
                    )
                    continue

            seen_output_paths.add(output_path)
            attachments_to_process.append(attachment)

        if not attachments_to_process:
            logger.info("All attachments already have existing output files.")
            return summarize_results(results)

        with ThreadPoolExecutor(
            max_workers=download_workers
        ) as download_executor, ProcessPoolExecutor() as conversion_executor:
            download_futures: dict = {}
            for attachment in attachments_to_process:
                file_path = _temp_path_for_attachment(temp_dir, attachment)
                future = download_executor.submit(
                    download_and_save, settings, attachment.attachment_key, file_path
                )
                download_futures[future] = (attachment, file_path)

            completed_downloads = 0
            for future in as_completed(download_futures):
                attachment, file_path = download_futures[future]
                try:
                    future.result()
                except Exception as exc:
                    logger.exception(
                        "Failed to download attachment %s: %s",
                        attachment.attachment_key,
                        exc,
                    )
                    continue

                completed_downloads += 1
                logger.debug(
                    "Downloaded %d/%d attachments",
                    completed_downloads,
                    len(attachments_to_process),
                )

                convert_future = conversion_executor.submit(
                    convert_attachment_to_markdown, attachment, file_path, settings
                )
                conversion_futures[convert_future] = attachment.attachment_key

            total_to_convert = len(conversion_futures)
            if total_to_convert == 0:
                logger.info("No downloaded attachments were ready for conversion.")
            else:
                completed_conversions = 0
                for future in as_completed(conversion_futures):
                    key = conversion_futures[future]
                    try:
                        result = future.result()
                        results.append(result)
                        completed_conversions += 1
                        logger.debug(
                            "Converted %d/%d attachments",
                            completed_conversions,
                            total_to_convert,
                        )
                    except Exception as exc:
                        logger.exception(
                            "Failed to convert attachment %s: %s", key, exc
                        )

    return summarize_results(results)


def _temp_path_for_attachment(base_dir: Path, attachment: AttachmentMetadata) -> Path:
    """Return a temporary path for a downloaded attachment.

    The path incorporates the Zotero attachment key and, when available, the
    original file extension to help Docling with format detection.
    """
    filename = attachment.filename or attachment.attachment_key
    suffix = Path(filename).suffix
    name = f"{attachment.attachment_key}{suffix}"
    return base_dir / name


def download_and_save(
    settings: ExportSettings, attachment_key: str, file_path: Path
) -> None:
    """Download a single attachment; designed to be run in a worker thread."""
    if settings.dry_run:
        return
    with ZoteroClient(settings) as client:
        client.download_attachment(attachment_key, file_path)


def summarize_results(results: Sequence[ConversionResult]) -> ExportSummary:
    """Aggregate individual conversion results into a summary."""
    converted = sum(result.status == "converted" for result in results)
    skipped = sum(result.status == "skipped" for result in results)
    dry_run = sum(result.status == "dry-run" for result in results)
    summary = ExportSummary(
        processed=len(results),
        converted=converted,
        skipped=skipped,
        dry_run=dry_run,
        output_paths=tuple(result.output for result in results),
    )

    logger.info(
        "Export complete: processed=%d converted=%d skipped=%d dry-run=%d",
        summary.processed,
        summary.converted,
        summary.skipped,
        summary.dry_run,
    )
    return summary
