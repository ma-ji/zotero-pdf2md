"""High-level orchestration for exporting Zotero PDFs to Markdown."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

from .converter import ConversionResult, convert_attachment_to_markdown
from .models import AttachmentMetadata
from .settings import ExportSettings
from .utils import get_logger
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
    """Export all matching Zotero PDF attachments to Markdown via the Web API."""
    logger.info("Starting export via Zotero Web API")
    for line in settings.to_cli_summary():
        logger.info(line)

    results: list[ConversionResult] = []

    with TemporaryDirectory(prefix="zotero-pdf2md-") as tmp_dir:
        temp_dir = Path(tmp_dir)

        with ZoteroClient(settings) as client:
            attachments = list(client.iter_pdf_attachments())

        total_attachments = len(attachments)
        if total_attachments == 0:
            logger.info("No attachments matched the requested filters.")
            return summarize_results([])

        logger.info("Found %d attachment(s) to process.", total_attachments)

        if settings.dry_run:
            for attachment in attachments:
                pdf_path = temp_dir / f"{attachment.attachment_key}.pdf"
                results.append(
                    convert_attachment_to_markdown(attachment, pdf_path, settings)
                )
            return summarize_results(results)

        download_workers = settings.max_workers or min(8, total_attachments)
        download_workers = max(1, download_workers)
        conversion_futures: dict = {}

        with ThreadPoolExecutor(
            max_workers=download_workers
        ) as download_executor, ProcessPoolExecutor() as conversion_executor:
            download_futures: dict = {}
            for attachment in attachments:
                pdf_path = temp_dir / f"{attachment.attachment_key}.pdf"
                future = download_executor.submit(
                    download_and_save, settings, attachment.attachment_key, pdf_path
                )
                download_futures[future] = (attachment, pdf_path)

            completed_downloads = 0
            for future in as_completed(download_futures):
                attachment, pdf_path = download_futures[future]
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
                    total_attachments,
                )

                convert_future = conversion_executor.submit(
                    convert_attachment_to_markdown, attachment, pdf_path, settings
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


def download_and_save(
    settings: ExportSettings, attachment_key: str, pdf_path: Path
) -> None:
    """Download a single attachment; designed to be run in a worker thread."""
    if settings.dry_run:
        return
    with ZoteroClient(settings) as client:
        client.download_attachment(attachment_key, pdf_path)


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
