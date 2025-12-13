"""High-level orchestration for exporting Zotero-managed attachments to Markdown."""

from __future__ import annotations

import gc
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence
import warnings

import torch
from joblib import Parallel, delayed

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import AcceleratorDevice

from .converter import (
    ConversionResult,
    convert_attachment_to_markdown,
    get_pipeline_options,
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


def export_library(settings: ExportSettings) -> ExportSummary:
    """Export all matching Zotero attachments to Markdown via the Web API.

    All imported file attachments are considered; conversion is delegated to
    Docling, which may skip unsupported formats.
    """
    # Suppress warnings
    warnings.filterwarnings("ignore")
    warnings.simplefilter(action="ignore", category=FutureWarning)

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
                file_path = _temp_path_for_attachment(temp_dir, attachment)
                results.append(
                    convert_attachment_to_markdown(attachment, file_path, settings)
                )
            return summarize_results(results)

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

        # Warmup
        logger.info("Performing model warmup (CPU)...")
        try:
            warmup_pipeline_options = get_pipeline_options(
                force_full_page_ocr=settings.force_full_page_ocr,
                do_picture_description=settings.do_picture_description,
                image_resolution_scale=settings.image_resolution_scale,
                device=AcceleratorDevice.CPU,
                num_threads=1,
            )
            DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=warmup_pipeline_options
                    )
                }
            )
            logger.info("Model warmup complete.")
        except Exception as e:
            logger.warning(f"Model warmup warning: {e}")

        # GPU Detection
        num_gpus = 0
        try:
            if torch.cuda.is_available():
                num_gpus = torch.cuda.device_count()
            logger.info(f"Detected {num_gpus} GPUs available.")
        except Exception as e:
            logger.warning(f"Could not detect GPUs: {e}")

        # Parallel Execution
        n_jobs = settings.max_workers or 4
        # If user set max_workers, use it. If not, default to something reasonable.
        # Reference used NJOBS=12. 
        if settings.max_workers is None:
             n_jobs = 12 # Default from reference
        
        logger.info(f"Starting parallel processing with {n_jobs} jobs...")
        
        # We need to make sure process_attachment_task can be pickled
        # It is defined below
        
        parallel_results = Parallel(n_jobs=n_jobs, backend="loky")(
            delayed(_process_attachment_task)(
                attachment, settings, temp_dir, i, num_gpus
            )
            for i, attachment in enumerate(attachments_to_process)
        )
        
        results.extend(parallel_results)

    return summarize_results(results)


def _process_attachment_task(
    attachment: AttachmentMetadata,
    settings: ExportSettings,
    temp_dir: Path,
    job_index: int,
    num_gpus_available: int,
) -> ConversionResult:
    """Worker function for processing a single attachment."""
    # Handle GPU assignment
    if settings.use_multi_gpu and num_gpus_available > 0:
        gpu_idx = job_index % num_gpus_available
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_idx)
    
    file_path = _temp_path_for_attachment(temp_dir, attachment)
    
    try:
        download_and_save(settings, attachment.attachment_key, file_path)
    except Exception as exc:
        logger.error(
            "Failed to download attachment %s: %s",
            attachment.attachment_key,
            exc,
            exc_info=True
        )
        # Return a failed result
        output_path = compute_output_path(attachment, settings.output_dir)
        return ConversionResult(
            source=file_path,
            output=output_path,
            status="skipped"
        )
    
    # Convert
    try:
        result = convert_attachment_to_markdown(attachment, file_path, settings)
    except Exception as exc:
        logger.error(
            "Error converting %s: %s", file_path, exc, exc_info=True
        )
        output_path = compute_output_path(attachment, settings.output_dir)
        result = ConversionResult(
             source=file_path,
             output=output_path,
             status="skipped"
        )
        
    # Cleanup memory
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
    
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
