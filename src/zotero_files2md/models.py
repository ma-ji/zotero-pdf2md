"""Datamodels representing Zotero attachments fetched via the Web API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping


@dataclass(slots=True, frozen=True)
class AttachmentMetadata:
    """Metadata describing a Zotero attachment retrieved from the Web API."""

    attachment_key: str
    parent_item_key: str | None
    title: str | None
    parent_title: str | None
    filename: str | None
    parent_citation_key: str | None = None
    collections: tuple[str, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)
    date_added: datetime | None = None
    date_modified: datetime | None = None

    def as_info(self) -> Mapping[str, object]:
        """Return a serialisable mapping of core metadata."""
        return {
            "attachment_key": self.attachment_key,
            "parent_item_key": self.parent_item_key,
            "title": self.title,
            "parent_title": self.parent_title,
            "parent_citation_key": self.parent_citation_key,
            "filename": self.filename,
            "collections": list(self.collections),
            "tags": list(self.tags),
            "date_added": self.date_added.isoformat() if self.date_added else None,
            "date_modified": self.date_modified.isoformat()
            if self.date_modified
            else None,
        }

    @property
    def label(self) -> str:
        """Human-friendly label combining parent and attachment titles."""
        if self.parent_title and self.title:
            if self.parent_title.strip().lower() == self.title.strip().lower():
                return self.parent_title
            return f"{self.parent_title} – {self.title}"
        return self.title or self.parent_title or self.attachment_key
