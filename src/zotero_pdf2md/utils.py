"""Utility helpers for the ``zotero_pdf2md`` package."""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .models import AttachmentMetadata

LOGGER_NAME = "zotero_pdf2md"


def get_logger() -> logging.Logger:
    """Return a module-level logger configured for the package."""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(levelname)s %(name)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


_slug_cleanup = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(value: str | None, fallback: str) -> str:
    """Create a filesystem-friendly slug.

    Args:
        value: Preferred text to slugify.
        fallback: Text to use when ``value`` is empty after sanitization.

    Returns:
        A slug containing only ``A-Za-z0-9._-`` characters.
    """
    text = value or ""
    text = unicodedata.normalize("NFKD", text).strip()
    text = _slug_cleanup.sub("-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    if not text:
        text = fallback
    return text[:120]  # keep filenames manageable


def ensure_directory(path: Path) -> Path:
    """Create the directory if it does not exist, and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def flatten(iterables: Iterable[Iterable[str]]) -> set[str]:
    """Flatten an iterable of iterables into a set of unique values."""
    result: set[str] = set()
    for iterable in iterables:
        result.update(iterable)
    return result


def compute_output_path(
    attachment: "AttachmentMetadata", output_dir: Path
) -> Path:
    """Compute the expected output path for an attachment.

    Args:
        attachment: Attachment metadata describing the PDF.
        output_dir: Base output directory for markdown files.

    Returns:
        The full path where the markdown file would be written.
    """
    parent_slug = slugify(
        attachment.parent_title, attachment.parent_item_key or "item"
    )
    filename_base = slugify(attachment.title, attachment.attachment_key)
    return output_dir / parent_slug / f"{filename_base}.md"
