"""High-level orchestration for exporting Zotero-managed attachments to Markdown."""

from __future__ import annotations

import gc
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import dataclass, replace
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import local
from typing import Mapping, Sequence

from .converter import (
    ConversionResult,
    convert_attachment_to_markdown,
)
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


@dataclass(slots=True, frozen=True)
class BatchExportRun:
    """Summary of a single batch entry."""

    collection_key: str
    output_dir: Path
    summary: ExportSummary


@dataclass(slots=True, frozen=True)
class BatchExportSummary:
    """Summary of a batch export run."""

    processed: int
    converted: int
    skipped: int
    dry_run: int
    output_paths: tuple[Path, ...]
    runs: tuple[BatchExportRun, ...]


def export_collections(
    base_settings: ExportSettings,
    collection_output_dirs: Mapping[str, Path],
) -> BatchExportSummary:
    """Export multiple collections, each to its own output directory.

    Args:
        base_settings: Shared settings used for each export run. The output
            directory and collection filter are overridden per collection.
        collection_output_dirs: Mapping of collection key -> output directory.

    Returns:
        BatchExportSummary with totals and per-collection results.
    """
    if not collection_output_dirs:
        msg = "At least one collection output mapping must be provided."
        raise ValueError(msg)

    runs: list[BatchExportRun] = []
    output_paths: list[Path] = []

    processed = converted = skipped = dry_run = 0

    for collection_key, output_dir in collection_output_dirs.items():
        run_settings = replace(
            base_settings,
            output_dir=Path(output_dir),
            collections={collection_key},
        )
        run_summary = export_library(run_settings)
        runs.append(
            BatchExportRun(
                collection_key=collection_key,
                output_dir=run_settings.output_dir,
                summary=run_summary,
            )
        )

        processed += run_summary.processed
        converted += run_summary.converted
        skipped += run_summary.skipped
        dry_run += run_summary.dry_run
        output_paths.extend(run_summary.output_paths)

    return BatchExportSummary(
        processed=processed,
        converted=converted,
        skipped=skipped,
        dry_run=dry_run,
        output_paths=tuple(output_paths),
        runs=tuple(runs),
    )


def export_library(settings: ExportSettings) -> ExportSummary:
    """Export all matching Zotero attachments to Markdown via the Web API.

    All imported file attachments are considered; conversion is delegated to
    Docling, which may skip unsupported formats.
    """
    logger.info("Starting export via Docling and Zotero Web API")
    for line in settings.to_cli_summary():
        logger.info(line)

    results: list[ConversionResult] = []

    with TemporaryDirectory(prefix="zotero-files2md-") as tmp_dir:
        temp_dir = Path(tmp_dir)

        with ZoteroClient(settings) as client:
            # Fetch all imported attachments regardless of MIME type
            attachments = list(client.iter_attachments())

        total_attachments = len(attachments)
        if total_attachments == 0:
            logger.info("No attachments matched the requested filters.")
            return summarize_results([])

        logger.info("Found %d attachment(s) to process.", total_attachments)

        if settings.dry_run:
            for attachment in attachments:
                output_path = compute_output_path(attachment, settings.output_dir)
                results.append(
                    ConversionResult(
                        source=Path(attachment.filename or attachment.attachment_key),
                        output=output_path,
                        status="dry-run",
                    )
                )
            return summarize_results(results)

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

            if output_path.exists() and not settings.overwrite:
                logger.info("Skipping existing file: %s", output_path)
                results.append(
                    ConversionResult(
                        source=Path(attachment.filename or attachment.attachment_key),
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

        if settings.use_multi_gpu:
            gpu_count = _detect_gpu_count()
        else:
            gpu_count = 0

        if settings.use_multi_gpu and gpu_count > 0:
            max_workers_total = settings.max_workers or len(attachments_to_process)
            max_workers_by_gpu = gpu_count * settings.workers_per_gpu
            total_workers = max(
                1,
                min(
                    len(attachments_to_process),
                    max_workers_total,
                    max_workers_by_gpu,
                ),
            )
            gpus_used = min(gpu_count, total_workers)
            gpu_ids = list(range(gpu_count))[:gpus_used]

            base_workers = total_workers // gpus_used
            remainder = total_workers % gpus_used
            processes_per_gpu = {
                gpu_id: base_workers + (1 if idx < remainder else 0)
                for idx, gpu_id in enumerate(gpu_ids)
            }
            logger.info(
                "Processing %d attachment(s) with %d GPU worker process(es) across %d GPU(s) (<= %d process(es) per GPU).",
                len(attachments_to_process),
                total_workers,
                gpus_used,
                settings.workers_per_gpu,
            )
            if total_workers > gpus_used:
                logger.warning(
                    "Multiple worker processes per GPU can trigger CUDA out-of-memory errors. "
                    "Consider lowering --workers-per-gpu or disabling picture description."
                )

            processed: list[ConversionResult | None] = [None] * len(
                attachments_to_process
            )
            with ExitStack() as stack:
                executors_by_gpu = {
                    gpu_id: stack.enter_context(
                        ProcessPoolExecutor(
                            max_workers=processes_per_gpu[gpu_id],
                            initializer=_init_worker,
                            initargs=(gpu_id,),
                            mp_context=get_context("spawn"),
                        )
                    )
                    for gpu_id in gpu_ids
                }
                executor_slots = [
                    executors_by_gpu[gpu_id]
                    for gpu_id in gpu_ids
                    for _ in range(processes_per_gpu[gpu_id])
                ]
                future_to_index = {}
                for idx, attachment in enumerate(attachments_to_process):
                    executor = executor_slots[idx % total_workers]
                    future = executor.submit(
                        _process_attachment, attachment, settings, temp_dir
                    )
                    future_to_index[future] = idx

                for future in as_completed(future_to_index):
                    processed[future_to_index[future]] = future.result()

            results.extend([result for result in processed if result is not None])
        else:
            max_workers = settings.max_workers or min(12, os.cpu_count() or 4)
            max_workers = max(1, min(max_workers, len(attachments_to_process)))
            logger.info(
                "Processing %d attachment(s) with %d worker thread(s).",
                len(attachments_to_process),
                max_workers,
            )

            processed: list[ConversionResult | None] = [None] * len(
                attachments_to_process
            )
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_index = {
                    executor.submit(_process_attachment, attachment, settings, temp_dir): idx
                    for idx, attachment in enumerate(attachments_to_process)
                }

                for future in as_completed(future_to_index):
                    processed[future_to_index[future]] = future.result()

            results.extend([result for result in processed if result is not None])

    return summarize_results(results)


_worker_local = local()


def _detect_gpu_count() -> int:
    try:
        import torch
    except Exception:
        return 0
    try:
        return torch.cuda.device_count() if torch.cuda.is_available() else 0
    except Exception:
        return 0


def _init_worker(gpu_id: int | None = None) -> None:
    if gpu_id is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)


def _get_download_client(settings: ExportSettings):
    key = (settings.library_id, settings.library_type, settings.api_key)
    cached_key = getattr(_worker_local, "zotero_key", None)
    cached_client = getattr(_worker_local, "zotero_client", None)

    if cached_client is None or cached_key != key:
        from pyzotero.zotero import Zotero as ZoteroAPI

        cached_client = ZoteroAPI(
            library_id=settings.library_id,
            library_type=settings.library_type,
            api_key=settings.api_key,
        )
        _worker_local.zotero_key = key
        _worker_local.zotero_client = cached_client

    return cached_client


def _download_attachment(settings: ExportSettings, attachment_key: str, destination: Path) -> None:
    client = _get_download_client(settings)
    binary = client.file(attachment_key)
    destination.write_bytes(binary)


def _maybe_free_worker_memory() -> None:
    try:
        import torch
    except Exception:
        return
    if not torch.cuda.is_available():
        return

    count = getattr(_worker_local, "cuda_cleanup_count", 0) + 1
    _worker_local.cuda_cleanup_count = count
    if count % 5 != 0:
        return

    torch.cuda.empty_cache()
    gc.collect()


def _process_attachment(
    attachment: AttachmentMetadata,
    settings: ExportSettings,
    temp_dir: Path,
) -> ConversionResult:
    output_path = compute_output_path(attachment, settings.output_dir)
    if output_path.exists() and not settings.overwrite:
        return ConversionResult(
            source=Path(attachment.filename or attachment.attachment_key),
            output=output_path,
            status="skipped",
        )

    file_path = _temp_path_for_attachment(temp_dir, attachment)

    try:
        _download_attachment(settings, attachment.attachment_key, file_path)
    except Exception as exc:
        logger.error(
            "Failed to download attachment %s: %s",
            attachment.attachment_key,
            exc,
            exc_info=True
        )
        return ConversionResult(
            source=file_path,
            output=output_path,
            status="skipped"
        )
    
    try:
        result = convert_attachment_to_markdown(attachment, file_path, settings)
    except Exception as exc:
        logger.error(
            "Error converting %s: %s", file_path, exc, exc_info=True
        )
        result = ConversionResult(
             source=file_path,
             output=output_path,
             status="skipped"
        )

    _maybe_free_worker_memory()
    
    return result


def _temp_path_for_attachment(base_dir: Path, attachment: AttachmentMetadata) -> Path:
    """Return a temporary path for a downloaded attachment.

    The path incorporates the Zotero attachment key and, when available, the
    original file extension to help Docling with format detection.
    """
    filename = attachment.filename or attachment.attachment_key
    suffix = Path(filename).suffix
    name = f"{attachment.attachment_key}{suffix}"
    return base_dir / name


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
