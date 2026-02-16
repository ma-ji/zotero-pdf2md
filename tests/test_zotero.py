from __future__ import annotations

from zotero_files2md.zotero import ZoteroClient


def test_extract_parent_citation_key_from_direct_field() -> None:
    parent = {"data": {"citationKey": "  smith2023foundations  "}}
    assert ZoteroClient._extract_parent_citation_key(parent) == "smith2023foundations"


def test_extract_parent_citation_key_from_extra() -> None:
    parent = {
        "data": {
            "extra": "Some note\nCitation Key: smith2023foundations\nAnother line",
        }
    }
    assert ZoteroClient._extract_parent_citation_key(parent) == "smith2023foundations"


def test_extract_parent_citation_key_missing() -> None:
    parent = {"data": {"extra": "No key here"}}
    assert ZoteroClient._extract_parent_citation_key(parent) is None
