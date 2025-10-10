"""Utilities for interacting with the Zotero Web API via PyZotero."""

from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from pyzotero import zotero as zotero_api
from pyzotero.zotero import Zotero as ZoteroAPI  # re-exported type

from .models import AttachmentMetadata
from .settings import ExportSettings
from .utils import get_logger

# logging.basicConfig(level=logging.DEBUG)
logger = get_logger()


class ZoteroClient(AbstractContextManager["ZoteroClient"]):
    """Provide read-only access to a Zotero library via the Web API."""

    def __init__(self, settings: ExportSettings) -> None:
        self.settings = settings
        self._client = ZoteroAPI(
            library_id=settings.library_id,
            library_type=settings.library_type,
            api_key=settings.api_key,
        )
        self._collection_name_by_key = self._load_collection_mappings()
        self._collection_filter_keys = self._resolve_collection_filters(
            settings.collections
        )
        self._tag_filters = {tag.lower() for tag in settings.tags}
        self._parent_cache: dict[str, dict] = {}

        logger.debug(
            "Initialised ZoteroClient for %s library %s",
            settings.library_type,
            settings.library_id,
        )

    # --- context manager protocol -------------------------------------------------
    def __enter__(self) -> "ZoteroClient":
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        # PyZotero uses HTTP sessions; nothing explicit to close.
        logger.debug("Closing ZoteroClient")

    # --- public API ---------------------------------------------------------------
    def iter_pdf_attachments(self) -> Iterator[AttachmentMetadata]:
        """Yield PDF attachments that satisfy configured filters."""
        yielded = 0
        seen_keys: set[str] = set()

        collections_to_fetch: Iterable[str | None]
        if self._collection_filter_keys:
            collections_to_fetch = self._collection_filter_keys
        else:
            collections_to_fetch = (None,)

        for collection_key in collections_to_fetch:
            start = 0
            while True:
                params: dict[str, object] = {
                    "itemType": "attachment",
                    "format": "json",
                    "attachmentContentType": "application/pdf",
                    "limit": self.settings.chunk_size,
                    "start": start,
                    "sort": "dateModified",
                    "direction": "desc",
                }

                if collection_key is not None:
                    batch = self._client.collection_items(
                        collection_key,
                        itemType=params["itemType"],
                        format=params["format"],
                        attachmentContentType=params["attachmentContentType"],
                        limit=params["limit"],
                        start=params["start"],
                        sort=params["sort"],
                        direction=params["direction"],
                    )
                else:
                    batch = self._client.items(**params)
                if not batch:
                    break

                for item in batch:
                    data = item.get("data", {})
                    key = data.get("key")
                    if not key or key in seen_keys:
                        continue
                    seen_keys.add(key)

                    if not self._is_downloadable_attachment(data):
                        continue

                    parent_key = data.get("parentItem")
                    parent = self._fetch_parent(parent_key) if parent_key else None

                    attachment_collections = self._resolve_collection_names(
                        data.get("collections") or []
                    )
                    parent_collections = (
                        self._resolve_collection_names(
                            parent.get("data", {}).get("collections") or []
                        )
                        if parent
                        else ()
                    )
                    all_collections = tuple(
                        sorted(set(attachment_collections + parent_collections))
                    )

                    attachment_tags = self._extract_tags(data.get("tags", ()))
                    parent_tags = (
                        self._extract_tags(parent.get("data", {}).get("tags", ()))
                        if parent
                        else ()
                    )
                    all_tags = tuple(sorted(set(attachment_tags + parent_tags)))

                    if self._collection_filter_keys and not self._match_collections(
                        data.get("collections") or [],
                        parent.get("data", {}).get("collections") or []
                        if parent
                        else [],
                    ):
                        continue

                    if self._tag_filters and not self._match_tags(all_tags):
                        continue

                    metadata = AttachmentMetadata(
                        attachment_key=data["key"],
                        parent_item_key=parent_key,
                        title=data.get("title"),
                        parent_title=parent.get("data", {}).get("title")
                        if parent
                        else None,
                        filename=data.get("filename"),
                        collections=all_collections,
                        tags=all_tags,
                        date_added=self._parse_timestamp(data.get("dateAdded")),
                        date_modified=self._parse_timestamp(data.get("dateModified")),
                    )
                    yield metadata
                    yielded += 1

                    if self.settings.limit and yielded >= self.settings.limit:
                        return

                start += len(batch)

        if yielded == 0:
            logger.info("No PDF attachments matched the specified filters.")

    def download_attachment(self, attachment_key: str, destination: Path) -> Path:
        """Download an attachment's binary content to ``destination``."""
        logger.debug("Downloading attachment %s to %s", attachment_key, destination)
        binary = self._client.file(attachment_key)
        destination.write_bytes(binary)
        return destination

    # --- internal helpers ---------------------------------------------------------
    def _load_collection_mappings(self) -> dict[str, str]:
        """Return mapping of collection key -> human-friendly name."""
        mappings: dict[str, str] = {}
        start = 0

        while True:
            logger.debug(
                "Fetching collections: limit=%d, start=%d",
                self.settings.chunk_size,
                start,
            )
            batch = self._client.collections(
                format="json",
                limit=self.settings.chunk_size,
                start=start,
            )
            if not batch:
                logger.debug("Received empty batch. Ending collection fetch.")
                break

            logger.debug("Received batch of %d collections.", len(batch))
            for collection in batch:
                data = collection.get("data", {})
                key = data.get("key")
                name = data.get("name")
                if key and name:
                    mappings[key] = name
            start += len(batch)

        logger.debug("Loaded %d collections", len(mappings))
        if logger.isEnabledFor(logging.DEBUG):
            import json

            logger.debug(
                "Loaded collection mappings: %s",
                json.dumps(mappings, indent=2, sort_keys=True),
            )
        return mappings

    def _resolve_collection_names(self, keys: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            self._collection_name_by_key[key]
            for key in keys
            if key in self._collection_name_by_key
        )

    def _resolve_collection_filters(self, names: Iterable[str]) -> set[str]:
        if not names:
            return set()
        provided = {key.strip() for key in names if key and key.strip()}
        if not provided:
            return set()

        valid = {key for key in provided if key in self._collection_name_by_key}
        missing = provided - valid

        if valid:
            logger.info(
                "Filtering by %d collection keys: %s",
                len(valid),
                sorted(valid),
            )
        if missing:
            logger.warning(
                "Collection keys %s were not found in library metadata. "
                "Ensure these are collection keys, not names. "
                "For further diagnostics, run with --log-level debug to see all loaded collections.",
                sorted(missing),
            )
        return valid

    def _match_collections(
        self,
        attachment_keys: Iterable[str],
        parent_keys: Iterable[str],
    ) -> bool:
        if not self._collection_filter_keys:
            return True
        all_keys = set(attachment_keys) | set(parent_keys)
        return bool(all_keys & self._collection_filter_keys)

    def _extract_tags(self, tags: Iterable[dict]) -> tuple[str, ...]:
        names = []
        for tag in tags or []:
            name = tag.get("tag")
            if name:
                names.append(name)
        return tuple(sorted(set(names)))

    def _match_tags(self, names: Iterable[str]) -> bool:
        if not self._tag_filters:
            return True
        lower = {name.lower() for name in names}
        return bool(lower & self._tag_filters)

    def _fetch_parent(self, parent_key: str | None) -> dict:
        if parent_key is None:
            return {}
        if parent_key not in self._parent_cache:
            try:
                self._parent_cache[parent_key] = self._client.item(
                    parent_key, format="json"
                )
            except zotero_api.ResourceNotFound:
                logger.warning(
                    "Parent item %s not found; continuing without metadata", parent_key
                )
                self._parent_cache[parent_key] = {}
        return self._parent_cache[parent_key]

    @staticmethod
    def _is_downloadable_attachment(data: dict) -> bool:
        if not data:
            return False

        link_mode = data.get("linkMode")
        if link_mode not in {"imported_file", "imported_url"}:
            logger.debug(
                "Skipping non-imported attachment %s with linkMode=%s",
                data.get("key"),
                link_mode,
            )
            return False

        if not data.get("key"):
            return False

        return True

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        value = value.strip()
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
