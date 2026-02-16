"""Utility helpers for the ``zotero_files2md`` package."""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from .settings import ReferenceFolderName

if TYPE_CHECKING:
    from .models import AttachmentMetadata

LOGGER_NAME = "zotero_files2md"


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


def _clean_slug_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).strip()
    text = _slug_cleanup.sub("-", text)
    return re.sub(r"-{2,}", "-", text).strip("-._")


def slugify(value: str | None, fallback: str) -> str:
    """Create a filesystem-friendly slug.

    Args:
        value: Preferred text to slugify.
        fallback: Text to use when ``value`` is empty after sanitization.

    Returns:
        A slug containing only ``A-Za-z0-9._-`` characters.
    """
    text = _clean_slug_text(value or "")
    if not text:
        text = _clean_slug_text(fallback)
    if not text:
        text = "item"
    return text[:120]  # keep filenames manageable


def ensure_directory(path: Path) -> Path:
    """Create the directory if it does not exist, and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def compute_output_path(
    attachment: "AttachmentMetadata",
    output_dir: Path,
    reference_folder_name: ReferenceFolderName = "citation-key",
) -> Path:
    """Compute the expected output path for an attachment.

    Args:
        attachment: Attachment metadata describing the source file.
        output_dir: Base output directory for markdown files.
        reference_folder_name: Naming strategy for each reference folder.

    Returns:
        The full path where the markdown file would be written.
    """
    if reference_folder_name == "item-title":
        parent_value = attachment.parent_title
        parent_fallback = attachment.parent_item_key or attachment.parent_citation_key or "item"
    elif reference_folder_name == "citation-key":
        parent_value = attachment.parent_citation_key or attachment.parent_title
        parent_fallback = attachment.parent_item_key or "item"
    else:
        msg = (
            "reference_folder_name must be one of: "
            f"'citation-key', 'item-title'. Got {reference_folder_name!r}."
        )
        raise ValueError(msg)

    parent_slug = slugify(parent_value, parent_fallback)
    filename_base = slugify(attachment.title, attachment.attachment_key)
    return output_dir / parent_slug / f"{filename_base}.md"
