"""Tools for exporting Zotero-managed PDF attachments to Markdown."""

from importlib import metadata

from .exporter import export_library

try:
    __version__ = metadata.version("zotero-pdf2md")
except metadata.PackageNotFoundError:  # pragma: no cover - fallback during development
    __version__ = "0.0.0"

__all__ = ["export_library", "__version__"]
