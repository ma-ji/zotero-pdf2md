"""PDF to Markdown conversion helpers using PyMuPDF4LLM."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pymupdf4llm

from .models import AttachmentMetadata
from .settings import ExportSettings
from .utils import ensure_directory, get_logger, slugify

logger = get_logger()


def convert_attachment_to_markdown(
    attachment: AttachmentMetadata,
    pdf_path: Path,
    settings: ExportSettings,
) -> "ConversionResult":
    """Convert a Zotero PDF attachment to a Markdown file.

    Args:
        attachment: Attachment metadata describing the PDF to convert.
        pdf_path: Path to a local PDF file downloaded from the Zotero API.
        settings: Export configuration specifying output directory and options.

    Returns:
        A :class:`ConversionResult` describing the export outcome.
    """
    logger.debug(
        "Converting attachment %s using PDF %s", attachment.attachment_key, pdf_path
    )

    output_dir = ensure_directory(
        settings.output_dir
        / slugify(attachment.parent_title, attachment.parent_item_key or "item")
    )

    filename_base = slugify(attachment.title, attachment.attachment_key)
    output_path = output_dir / f"{filename_base}.md"

    if output_path.exists() and not settings.overwrite:
        logger.info("Skipping existing file: %s", output_path)
        return ConversionResult(
            source=pdf_path,
            output=output_path,
            status="skipped",
        )

    if settings.dry_run:
        logger.info("[dry-run] Would write %s", output_path)
        return ConversionResult(
            source=pdf_path,
            output=output_path,
            status="dry-run",
        )

    if not pdf_path.exists():
        msg = f"PDF file not found for conversion: {pdf_path}"
        raise FileNotFoundError(msg)

    try:
        markdown = _render_markdown(pdf_path, settings.markdown_options)
        output_path.write_bytes(markdown.encode("utf-8"))
        logger.info("Wrote %s", output_path)
    except Exception as exc:
        logger.error("Error converting %s: %s", pdf_path, exc, exc_info=True)
        return ConversionResult(
            source=pdf_path,
            output=output_path,
            status="skipped",
        )
    return ConversionResult(
        source=pdf_path,
        output=output_path,
        status="converted",
    )


@dataclass(slots=True, frozen=True)
class ConversionResult:
    """Describe the outcome of converting a single PDF attachment."""

    source: Path
    output: Path
    status: Literal["converted", "skipped", "dry-run"]


def _render_markdown(pdf_path: Path, markdown_options: dict[str, Any]) -> str:
    options = dict(markdown_options)
    options.setdefault("doc", str(pdf_path))
    # Ensure doc parameter is not duplicated
    return pymupdf4llm.to_markdown(**options)
