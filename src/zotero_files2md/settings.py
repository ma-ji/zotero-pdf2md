"""Configuration management for the ``zotero_files2md`` exporter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Sequence


LibraryType = Literal["user", "group"]
ImageProcessing = Literal["embed", "placeholder", "drop"]


def parse_collection_output_pairs(values: Iterable[str] | None) -> dict[str, Path]:
    """Parse CLI-style ``COLLECTION_KEY=OUTPUT_DIR`` pairs.

    Args:
        values: Iterable of strings formatted as ``COLLECTION_KEY=OUTPUT_DIR``.

    Returns:
        An ordered mapping of collection key to output directory path.
    """
    mapping: dict[str, Path] = {}
    if not values:
        return mapping

    for item in values:
        raw = str(item).strip()
        if not raw:
            continue
        if "=" not in raw:
            msg = "Collection outputs must be specified as COLLECTION_KEY=OUTPUT_DIR pairs."
            raise ValueError(msg)

        collection_key, output_dir = raw.split("=", 1)
        collection_key = collection_key.strip()
        output_dir = output_dir.strip()

        if not collection_key:
            msg = "Collection key cannot be empty in COLLECTION_KEY=OUTPUT_DIR."
            raise ValueError(msg)
        if not output_dir:
            msg = f"Output directory cannot be empty for collection {collection_key!r}."
            raise ValueError(msg)
        if collection_key in mapping:
            msg = f"Duplicate collection key in mapping: {collection_key!r}."
            raise ValueError(msg)

        mapping[collection_key] = Path(output_dir)

    return mapping


@dataclass(slots=True)
class ExportSettings:
    """Configuration for exporting Zotero attachments to Markdown."""

    api_key: str
    library_id: str
    library_type: LibraryType
    output_dir: Path

    # Filters
    collections: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)

    # Conversion options
    overwrite: bool = False
    dry_run: bool = False
    limit: int | None = None
    chunk_size: int = 100
    max_workers: int | None = None
    workers_per_gpu: int = 1
    
    # Docling specific options
    force_full_page_ocr: bool = False
    do_picture_description: bool = False
    image_resolution_scale: float = 4.0
    image_processing: ImageProcessing = "embed"
    use_multi_gpu: bool = True

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

        if self.workers_per_gpu <= 0:
            msg = "workers_per_gpu must be a positive integer."
            raise ValueError(msg)

        self.image_processing = self.image_processing.strip().lower()  # type: ignore[assignment]
        if self.image_processing not in {"embed", "placeholder", "drop"}:
            msg = (
                "image_processing must be one of: 'embed', 'placeholder', 'drop'. "
                f"Got {self.image_processing!r}."
            )
            raise ValueError(msg)

        self.output_dir = self.output_dir.expanduser().resolve()

        self.collections = {c.strip() for c in self.collections if c.strip()}
        self.tags = {t.strip() for t in self.tags if t.strip()}

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
        dry_run: bool = False,
        limit: int | None = None,
        chunk_size: int = 100,
        max_workers: int | None = None,
        workers_per_gpu: int = 1,
        force_full_page_ocr: bool = False,
        do_picture_description: bool = False,
        image_resolution_scale: float = 4.0,
        image_processing: ImageProcessing = "embed",
        use_multi_gpu: bool = True,
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
            dry_run=dry_run,
            limit=limit,
            chunk_size=chunk_size,
            max_workers=max_workers,
            workers_per_gpu=workers_per_gpu,
            force_full_page_ocr=force_full_page_ocr,
            do_picture_description=do_picture_description,
            image_resolution_scale=image_resolution_scale,
            image_processing=image_processing,
            use_multi_gpu=use_multi_gpu,
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
            f"Dry run: {self.dry_run}",
            f"Chunk size: {self.chunk_size}",
            f"Max workers: {self.max_workers or 'auto'}",
            f"Workers per GPU: {self.workers_per_gpu}",
            f"Force full page OCR: {self.force_full_page_ocr}",
            f"Picture description: {self.do_picture_description}",
            f"Image resolution scale: {self.image_resolution_scale}",
            f"Image processing: {self.image_processing}",
            f"Use multi GPU: {self.use_multi_gpu}",
        ]
