"""Configuration management for the ``zotero_pdf2md`` exporter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence


LibraryType = Literal["user", "group"]


@dataclass(slots=True)
class ExportSettings:
    """Configuration for exporting Zotero PDFs to Markdown."""

    api_key: str
    library_id: str
    library_type: LibraryType
    output_dir: Path

    # Filters
    collections: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)

    # Conversion options
    overwrite: bool = False
    skip_existing: bool = False
    dry_run: bool = False
    limit: int | None = None
    chunk_size: int = 100
    max_workers: int | None = None
    markdown_options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.api_key = self.api_key.strip()
        if not self.api_key:
            msg = "Zotero API key must be provided."
            raise ValueError(msg)

        self.library_id = str(self.library_id).strip()
        if not self.library_id:
            msg = "Zotero library ID must be provided."
            raise ValueError(msg)

        if self.library_type not in {"user", "group"}:
            msg = f"Invalid library type: {self.library_type!r}. Expected 'user' or 'group'."
            raise ValueError(msg)

        if self.limit is not None and self.limit <= 0:
            msg = "Limit must be a positive integer when provided."
            raise ValueError(msg)

        if self.chunk_size <= 0:
            msg = "chunk_size must be a positive integer."
            raise ValueError(msg)

        if self.max_workers is not None and self.max_workers <= 0:
            msg = "max_workers must be positive when provided."
            raise ValueError(msg)

        self.output_dir = self.output_dir.expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.collections = {c.strip() for c in self.collections if c.strip()}
        self.tags = {t.strip() for t in self.tags if t.strip()}
        self.markdown_options = dict(self.markdown_options)

    @classmethod
    def from_cli_args(
        cls,
        *,
        api_key: str,
        library_id: str,
        library_type: LibraryType,
        output_dir: str | Path,
        collections: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
        overwrite: bool = False,
        skip_existing: bool = False,
        dry_run: bool = False,
        limit: int | None = None,
        chunk_size: int = 100,
        max_workers: int | None = None,
        markdown_options: Mapping[str, Any] | None = None,
    ) -> "ExportSettings":
        """Instantiate settings from CLI-friendly arguments."""
        return cls(
            api_key=api_key,
            library_id=library_id,
            library_type=library_type,
            output_dir=Path(output_dir),
            collections=set(collections or ()),
            tags=set(tags or ()),
            overwrite=overwrite,
            skip_existing=skip_existing,
            dry_run=dry_run,
            limit=limit,
            chunk_size=chunk_size,
            max_workers=max_workers,
            markdown_options=dict(markdown_options or {}),
        )

    def describe_filters(self) -> str:
        """Return a human-friendly description of active filters."""
        parts: list[str] = []
        if self.collections:
            parts.append(f"collections={sorted(self.collections)}")
        if self.tags:
            parts.append(f"tags={sorted(self.tags)}")
        if self.limit:
            parts.append(f"limit={self.limit}")
        if not parts:
            return "no filters"
        return ", ".join(parts)

    def to_cli_summary(self) -> Sequence[str]:
        """Return summary lines suitable for logging or CLI output."""
        return [
            f"Library type: {self.library_type}",
            f"Library ID: {self.library_id}",
            "Using Zotero Web API",
            f"Output directory: {self.output_dir}",
            f"Filters: {self.describe_filters()}",
            f"Overwrite existing files: {self.overwrite}",
            f"Skip existing files: {self.skip_existing}",
            f"Dry run: {self.dry_run}",
            f"Chunk size: {self.chunk_size}",
            f"Max workers: {self.max_workers or 'auto'}",
            f"Markdown options: {self.markdown_options or {}}",
        ]
