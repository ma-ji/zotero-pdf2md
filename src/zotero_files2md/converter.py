"""Attachment-to-Markdown conversion helpers using Docling."""

from __future__ import annotations

import gc
from dataclasses import dataclass
from pathlib import Path
from threading import local
from typing import Literal

from .models import AttachmentMetadata
from .settings import ExportSettings
from .utils import compute_output_path, ensure_directory, get_logger

logger = get_logger()
_converter_local = local()

PAGE_BREAK_MARKER = "--- Page Break ---"
PAGE_BREAK_PLACEHOLDER = f"\n\n{PAGE_BREAK_MARKER}\n\n"
SECTION_MARKER_PREFIX = "[[[PAGE:"
SECTION_MARKER_SUFFIX = "]]]"


def convert_attachment_to_markdown(
    attachment: AttachmentMetadata,
    file_path: Path,
    settings: ExportSettings,
) -> "ConversionResult":
    """Convert a Zotero attachment to a Markdown file using Docling.

    Args:
        attachment: Attachment metadata describing the file to convert.
        file_path: Path to a local file downloaded from the Zotero API.
        settings: Export configuration specifying output directory and options.

    Returns:
        A :class:`ConversionResult` describing the export outcome.
    """
    logger.debug(
        "Converting attachment %s using file %s", attachment.attachment_key, file_path
    )

    output_path = compute_output_path(
        attachment,
        settings.output_dir,
        settings.reference_folder_name,
    )

    if output_path.exists() and not settings.overwrite:
        logger.info("Skipping existing file: %s", output_path)
        return ConversionResult(
            source=file_path,
            output=output_path,
            status="skipped",
        )

    if settings.dry_run:
        logger.info("[dry-run] Would write %s", output_path)
        return ConversionResult(
            source=file_path,
            output=output_path,
            status="dry-run",
        )

    ensure_directory(output_path.parent)

    if not file_path.exists():
        msg = f"File not found for conversion: {file_path}"
        raise FileNotFoundError(msg)

    try:
        markdown = _render_markdown(file_path, settings)
    except Exception as exc:
        if _is_cuda_oom(exc):
            logger.warning(
                "CUDA out-of-memory while converting %s; retrying conversion on CPU.",
                file_path,
            )
            _reset_converter_cache()
            _free_torch_memory()
            try:
                from docling.datamodel.pipeline_options import AcceleratorDevice

                markdown = _render_markdown(
                    file_path, settings, device=AcceleratorDevice.CPU
                )
            except Exception as retry_exc:
                logger.error(
                    "Error converting %s after CPU retry: %s",
                    file_path,
                    retry_exc,
                    exc_info=True,
                )
                return ConversionResult(
                    source=file_path,
                    output=output_path,
                    status="skipped",
                )
        else:
            logger.error("Error converting %s: %s", file_path, exc, exc_info=True)
            return ConversionResult(
                source=file_path,
                output=output_path,
                status="skipped",
            )
    try:
        output_path.write_bytes(markdown.encode("utf-8"))
        logger.info("Wrote %s", output_path)
    except Exception as exc:
        logger.error("Error converting %s: %s", file_path, exc, exc_info=True)
        return ConversionResult(
            source=file_path,
            output=output_path,
            status="skipped",
        )
    return ConversionResult(
        source=file_path,
        output=output_path,
        status="converted",
    )


@dataclass(slots=True, frozen=True)
class ConversionResult:
    """Describe the outcome of converting a single attachment."""

    source: Path
    output: Path
    status: Literal["converted", "skipped", "dry-run"]


def get_pipeline_options(
    force_full_page_ocr: bool,
    do_picture_description: bool,
    image_resolution_scale: float,
    device: AcceleratorDevice | None = None,
    num_threads: int = 4,
) -> PdfPipelineOptions:
    from docling.datamodel.pipeline_options import (
        AcceleratorDevice,
        AcceleratorOptions,
        PdfPipelineOptions,
        TableFormerMode,
    )

    if device is None:
        device = AcceleratorDevice.AUTO

    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = True
    pipeline_options.do_picture_description = do_picture_description
    pipeline_options.do_formula_enrichment = True
    pipeline_options.do_code_enrichment = True
    pipeline_options.ocr_options.force_full_page_ocr = force_full_page_ocr
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
    pipeline_options.table_structure_options.do_cell_matching = True
    pipeline_options.images_scale = image_resolution_scale

    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=num_threads, device=device
    )
    return pipeline_options


def _render_markdown(
    file_path: Path,
    settings: ExportSettings,
    device: AcceleratorDevice | None = None,
) -> str:
    """Render a local document to Markdown using Docling."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import AcceleratorDevice
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling_core.types.doc.base import ImageRefMode

    if device is None:
        device = _resolve_docling_device(settings, AcceleratorDevice)

    cache_key = (
        settings.force_full_page_ocr,
        settings.do_picture_description,
        settings.image_resolution_scale,
        device,
    )
    cached_key = getattr(_converter_local, "key", None)
    converter = getattr(_converter_local, "converter", None)

    if converter is None or cached_key != cache_key:
        pipeline_options = get_pipeline_options(
            force_full_page_ocr=settings.force_full_page_ocr,
            do_picture_description=settings.do_picture_description,
            image_resolution_scale=settings.image_resolution_scale,
            device=device,
        )
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        _converter_local.key = cache_key
        _converter_local.converter = converter

    result = converter.convert(str(file_path))

    if result.document is None:
        msg = f"Docling conversion failed for {file_path}: {result.status}"
        raise RuntimeError(msg)

    image_processing = settings.image_processing
    if image_processing == "embed":
        image_mode = ImageRefMode.EMBEDDED
        image_placeholder = "<!-- image -->"
    elif image_processing == "placeholder":
        image_mode = ImageRefMode.PLACEHOLDER
        image_placeholder = "<!-- image -->"
    elif image_processing == "drop":
        image_mode = ImageRefMode.PLACEHOLDER
        image_placeholder = ""
    else:  # pragma: no cover - validated by ExportSettings
        image_mode = ImageRefMode.EMBEDDED
        image_placeholder = "<!-- image -->"

    if settings.page_sections:
        return _render_markdown_with_page_sections(
            document=result.document,
            image_mode=image_mode,
            image_placeholder=image_placeholder,
        )

    return result.document.export_to_markdown(
        image_placeholder=image_placeholder,
        image_mode=image_mode,
        page_break_placeholder=PAGE_BREAK_PLACEHOLDER,
    )


def _render_markdown_with_page_sections(
    *,
    document,
    image_mode,
    image_placeholder: str,
) -> str:
    """Render Markdown with explicit machine-safe page header/body/footer sections."""
    from docling_core.types.doc.document import ContentLayer
    from docling_core.types.doc.labels import DocItemLabel

    page_numbers = _get_page_numbers(document)
    if not page_numbers:
        return document.export_to_markdown(
            image_placeholder=image_placeholder,
            image_mode=image_mode,
            page_break_placeholder=PAGE_BREAK_PLACEHOLDER,
        )

    chunks: list[str] = []
    last_idx = len(page_numbers) - 1
    for idx, page_no in enumerate(page_numbers):
        header_text = document.export_to_markdown(
            page_no=page_no,
            labels={DocItemLabel.PAGE_HEADER},
            included_content_layers={ContentLayer.FURNITURE},
        ).strip()
        body_text = document.export_to_markdown(
            page_no=page_no,
            image_placeholder=image_placeholder,
            image_mode=image_mode,
            included_content_layers={ContentLayer.BODY},
        ).strip()
        footer_text = document.export_to_markdown(
            page_no=page_no,
            labels={DocItemLabel.PAGE_FOOTER},
            included_content_layers={ContentLayer.FURNITURE},
        ).strip()

        chunks.extend(_format_section_block(page_no, "HEADER", header_text))
        chunks.extend(_format_section_block(page_no, "BODY", body_text))
        chunks.extend(_format_section_block(page_no, "FOOTER", footer_text))

        if idx < last_idx:
            chunks.append(PAGE_BREAK_MARKER)

    return "\n\n".join(chunks).strip()


def _get_page_numbers(document) -> list[int]:
    from docling_core.types.doc.document import ContentLayer

    page_numbers = sorted(document.pages.keys())
    if page_numbers:
        return page_numbers

    discovered: set[int] = set()
    for item, _ in document.iterate_items(
        with_groups=True,
        included_content_layers=set(ContentLayer),
    ):
        if hasattr(item, "prov") and item.prov:
            discovered.update(prov.page_no for prov in item.prov)
    return sorted(discovered)


def _format_section_block(page_no: int, section: str, content: str) -> list[str]:
    start = _section_marker(page_no, section, "START")
    end = _section_marker(page_no, section, "END")
    if content:
        payload = content
    else:
        payload = _section_marker(page_no, section, "EMPTY")
    return [start, payload, end]


def _section_marker(page_no: int, section: str, boundary: str) -> str:
    return f"{SECTION_MARKER_PREFIX}{page_no}|{section}|{boundary}{SECTION_MARKER_SUFFIX}"


def _resolve_docling_device(settings: ExportSettings, device_type) -> "AcceleratorDevice":
    if not settings.use_multi_gpu:
        return device_type.AUTO
    try:
        import torch
    except Exception:
        return device_type.AUTO
    try:
        if torch.cuda.is_available():
            return device_type.CUDA
    except Exception:
        return device_type.AUTO
    return device_type.AUTO


def _reset_converter_cache() -> None:
    for name in ("key", "converter"):
        if hasattr(_converter_local, name):
            delattr(_converter_local, name)


def _is_cuda_oom(exc: BaseException) -> bool:
    def iter_chain(err: BaseException):
        seen: set[int] = set()
        current: BaseException | None = err
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            yield current
            current = current.__cause__ or current.__context__

    for err in iter_chain(exc):
        message = str(err).lower()
        if "cuda out of memory" in message:
            return True
        if "out of memory" in message and "cuda" in message:
            return True
        try:
            import torch

            if isinstance(err, torch.OutOfMemoryError):
                return True
        except Exception:
            continue
    return False


def _free_torch_memory() -> None:
    try:
        import torch
    except Exception:
        return

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        try:
            torch.cuda.ipc_collect()
        except Exception:
            pass
    gc.collect()
