"""Utilities for interacting with the Zotero Web API via PyZotero."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
import re
from typing import Iterable, Iterator

from pyzotero import zotero as zotero_api
from pyzotero.zotero import Zotero as ZoteroAPI  # re-exported type

from .models import AttachmentMetadata
from .settings import ExportSettings
from .utils import get_logger

logger = get_logger()
_citation_key_pattern = re.compile(
    r"^\s*(?:citation\s*key|citationkey|citekey)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)


class ZoteroClient(AbstractContextManager["ZoteroClient"]):
    """Provide read-only access to a Zotero library via the Web API."""

    def __init__(self, settings: ExportSettings) -> None:
        self.settings = settings
        self._client = ZoteroAPI(
            library_id=settings.library_id,
            library_type=settings.library_type,
            api_key=settings.api_key,
        )
        self._collection_filter_keys = set(settings.collections)
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
    def iter_attachments(
        self, *, content_types: Iterable[str] | None = None
    ) -> Iterator[AttachmentMetadata]:
        """Yield file attachments that satisfy configured filters.

        Args:
            content_types: Optional iterable of MIME types to include (e.g.
                {"application/pdf", "application/msword"}). When omitted,
                all imported attachments are yielded regardless of type.
        """
        yielded = 0
        seen_keys: set[str] = set()

        content_type_filter = (
            {ct.lower() for ct in content_types} if content_types else None
        )

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

                    # Optional MIME-type filtering based on stored contentType
                    if content_type_filter:
                        content_type = (data.get("contentType") or "").lower()
                        if content_type not in content_type_filter:
                            continue

                    parent_key = data.get("parentItem")
                    parent = self._fetch_parent(parent_key) if parent_key else None

                    attachment_collection_keys = tuple(data.get("collections") or ())
                    parent_collection_keys = (
                        tuple(parent.get("data", {}).get("collections") or ())
                        if parent
                        else ()
                    )
                    all_collections = tuple(
                        sorted(
                            set(attachment_collection_keys)
                            | set(parent_collection_keys)
                        )
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
                        parent_citation_key=self._extract_parent_citation_key(parent)
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
            logger.info("No attachments matched the specified filters.")
    # --- internal helpers ---------------------------------------------------------

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
    def _extract_parent_citation_key(parent: dict) -> str | None:
        data = parent.get("data", {}) if parent else {}

        direct_key = data.get("citationKey")
        if isinstance(direct_key, str):
            cleaned = direct_key.strip()
            if cleaned:
                return cleaned

        extra = data.get("extra")
        if not isinstance(extra, str):
            return None

        for line in extra.splitlines():
            match = _citation_key_pattern.match(line)
            if match:
                key = match.group(1).strip()
                if key:
                    return key

        return None

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
