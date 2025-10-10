from __future__ import annotations

from pathlib import Path

import pytest

from zotero_pdf2md.settings import ExportSettings


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
    assert "Max workers: 4" in summary[8]


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
