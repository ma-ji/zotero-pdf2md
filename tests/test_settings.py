from __future__ import annotations

from pathlib import Path

import pytest

from zotero_files2md.settings import ExportSettings
from zotero_files2md.settings import parse_collection_output_pairs
from zotero_files2md.utils import compute_output_path
from zotero_files2md.models import AttachmentMetadata


def test_settings_initialisation(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    settings = ExportSettings.from_cli_args(
        api_key="  abc123  ",
        library_id=" 654321 ",
        library_type="user",
        output_dir=output_dir,
        collections=[" Collection ", " "],
        tags=["Tag", ""],
        overwrite=True,
        dry_run=True,
        limit=5,
        chunk_size=25,
        max_workers=4,
        image_processing="PLACEHOLDER",
        reference_folder_name="ITEM-TITLE",
    )

    assert settings.api_key == "abc123"
    assert settings.library_id == "654321"
    assert settings.library_type == "user"
    assert settings.output_dir == output_dir.resolve()
    assert settings.collections == {"Collection"}
    assert settings.tags == {"Tag"}
    assert settings.overwrite is True
    assert settings.dry_run is True
    assert settings.limit == 5
    assert settings.chunk_size == 25
    assert settings.max_workers == 4
    assert settings.workers_per_gpu == 1
    assert settings.image_processing == "placeholder"
    assert settings.reference_folder_name == "item-title"

    summary = settings.to_cli_summary()
    assert "Library type: user" in summary
    assert "Library ID: 654321" in summary
    assert "Reference folder name: item-title" in summary
    assert "Filters: collections=['Collection'], tags=['Tag'], limit=5" in summary
    assert "Max workers: 4" in summary
    assert "Workers per GPU: 1" in summary
    assert "Image processing: placeholder" in summary


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"api_key": "", "library_id": "1", "library_type": "user"}, ValueError),
        ({"api_key": "abc", "library_id": "", "library_type": "user"}, ValueError),
        ({"api_key": "abc", "library_id": "1", "library_type": "org"}, ValueError),
        (
            {"api_key": "abc", "library_id": "1", "library_type": "user", "limit": 0},
            ValueError,
        ),
        (
            {
                "api_key": "abc",
                "library_id": "1",
                "library_type": "user",
                "chunk_size": 0,
            },
            ValueError,
        ),
        (
            {
                "api_key": "abc",
                "library_id": "1",
                "library_type": "user",
                "max_workers": 0,
            },
            ValueError,
        ),
        (
            {
                "api_key": "abc",
                "library_id": "1",
                "library_type": "user",
                "workers_per_gpu": 0,
            },
            ValueError,
        ),
        (
            {
                "api_key": "abc",
                "library_id": "1",
                "library_type": "user",
                "image_processing": "unknown",
            },
            ValueError,
        ),
        (
            {
                "api_key": "abc",
                "library_id": "1",
                "library_type": "user",
                "reference_folder_name": "unknown",
            },
            ValueError,
        ),
    ],
)
def test_settings_validation_errors(
    tmp_path: Path, kwargs: dict, error: type[Exception]
) -> None:
    base = {
        "api_key": "key",
        "library_id": "1",
        "library_type": "user",
        "output_dir": tmp_path / "out",
    }
    base.update(kwargs)
    with pytest.raises(error):
        ExportSettings(**base)


def test_compute_output_path(tmp_path: Path) -> None:
    """Test the default reference-folder naming strategy."""
    attachment = AttachmentMetadata(
        attachment_key="ABC123",
        parent_item_key="PARENT1",
        title="Test Paper",
        parent_title="Author 2023",
        parent_citation_key="smith2023foundations",
        filename="test.pdf",
    )

    result = compute_output_path(attachment, tmp_path)
    expected = tmp_path / "smith2023foundations" / "Test-Paper.md"
    assert result == expected


def test_compute_output_path_with_item_title_folders(tmp_path: Path) -> None:
    attachment = AttachmentMetadata(
        attachment_key="ABC123",
        parent_item_key="PARENT1",
        title="Test Paper",
        parent_title="Author 2023",
        parent_citation_key="smith2023foundations",
        filename="test.pdf",
    )

    result = compute_output_path(attachment, tmp_path, "item-title")
    expected = tmp_path / "Author-2023" / "Test-Paper.md"
    assert result == expected


def test_compute_output_path_with_missing_citation_key(tmp_path: Path) -> None:
    """Test citation-key mode fallback to parent title when key is missing."""
    attachment = AttachmentMetadata(
        attachment_key="ABC123",
        parent_item_key="PARENT1",
        title="Test Paper",
        parent_title="Author 2023",
        filename="test.pdf",
    )

    result = compute_output_path(attachment, tmp_path, "citation-key")
    expected = tmp_path / "Author-2023" / "Test-Paper.md"
    assert result == expected


def test_compute_output_path_with_fallback(tmp_path: Path) -> None:
    """Test compute_output_path fallback when metadata is missing."""
    attachment = AttachmentMetadata(
        attachment_key="ABC123",
        parent_item_key="PARENT1",
        title=None,
        parent_title=None,
        filename="test.pdf",
    )

    result = compute_output_path(attachment, tmp_path)
    expected = tmp_path / "PARENT1" / "ABC123.md"
    assert result == expected


def test_parse_collection_output_pairs() -> None:
    mapping = parse_collection_output_pairs(
        [
            " ABCD1234 = ./out/a ",
            "EFGH5678=./out/b",
        ]
    )
    assert list(mapping.keys()) == ["ABCD1234", "EFGH5678"]
    assert mapping["ABCD1234"] == Path("./out/a")
    assert mapping["EFGH5678"] == Path("./out/b")


@pytest.mark.parametrize(
    "value",
    [
        ["missing-separator"],
        ["=./out"],
        ["KEY="],
        ["KEY=./out", "KEY=./out2"],
    ],
)
def test_parse_collection_output_pairs_validation(value: list[str]) -> None:
    with pytest.raises(ValueError):
        parse_collection_output_pairs(value)
