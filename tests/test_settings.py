from __future__ import annotations

from pathlib import Path

import pytest

from zotero_pdf2md.settings import ExportSettings
from zotero_pdf2md.utils import compute_output_path
from zotero_pdf2md.models import AttachmentMetadata


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
        markdown_options={"write_images": "true"},
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
    assert settings.markdown_options == {"write_images": "true"}

    summary = settings.to_cli_summary()
    assert "Library type: user" in summary[0]
    assert "Library ID: 654321" in summary[1]
    assert "Filters: collections=['Collection'], tags=['Tag'], limit=5" in summary[4]
    assert "Max workers: 4" in summary[9]


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


def test_skip_existing_setting(tmp_path: Path) -> None:
    """Test that skip_existing setting works correctly."""
    output_dir = tmp_path / "output"

    # Default should be False
    settings_default = ExportSettings.from_cli_args(
        api_key="test",
        library_id="123",
        library_type="user",
        output_dir=output_dir,
    )
    assert settings_default.skip_existing is False

    # When set to True
    settings_enabled = ExportSettings.from_cli_args(
        api_key="test",
        library_id="123",
        library_type="user",
        output_dir=output_dir,
        skip_existing=True,
    )
    assert settings_enabled.skip_existing is True

    # Should appear in CLI summary
    summary = settings_enabled.to_cli_summary()
    assert any("Skip existing files: True" in line for line in summary)


def test_compute_output_path(tmp_path: Path) -> None:
    """Test that compute_output_path returns the expected path."""
    attachment = AttachmentMetadata(
        attachment_key="ABC123",
        parent_item_key="PARENT1",
        title="Test Paper",
        parent_title="Author 2023",
        filename="test.pdf",
    )

    result = compute_output_path(attachment, tmp_path)
    expected = tmp_path / "Author-2023" / "Test-Paper.md"
    assert result == expected


def test_compute_output_path_with_fallback(tmp_path: Path) -> None:
    """Test compute_output_path when title or parent_title are None."""
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
