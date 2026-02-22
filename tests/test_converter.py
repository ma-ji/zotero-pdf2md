from __future__ import annotations

import pytest

pytest.importorskip("docling_core", reason="docling_core is required for converter page-section tests")

from docling_core.types.doc import DoclingDocument
from docling_core.types.doc.base import BoundingBox, CoordOrigin, ImageRefMode, Size
from docling_core.types.doc.document import ContentLayer, ProvenanceItem
from docling_core.types.doc.labels import DocItemLabel

from zotero_files2md.converter import _render_markdown_with_page_sections


def _prov(page_no: int, top: float, width: float = 120.0) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(
            l=72.0,
            t=top,
            r=72.0 + width,
            b=top + 12.0,
            coord_origin=CoordOrigin.TOPLEFT,
        ),
        charspan=(0, 0),
    )


def test_page_sections_include_header_body_footer_and_page_break() -> None:
    doc = DoclingDocument(name="sample")
    doc.add_page(page_no=1, size=Size(width=595, height=842))
    doc.add_page(page_no=2, size=Size(width=595, height=842))

    # Page 1
    doc.add_text(
        label=DocItemLabel.PAGE_HEADER,
        text="Proceedings 2026",
        prov=_prov(1, top=36.0),
        content_layer=ContentLayer.FURNITURE,
    )
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="Body content on page one.",
        prov=_prov(1, top=120.0, width=240.0),
        content_layer=ContentLayer.BODY,
    )
    doc.add_text(
        label=DocItemLabel.PAGE_FOOTER,
        text="1",
        prov=_prov(1, top=810.0, width=24.0),
        content_layer=ContentLayer.FURNITURE,
    )

    # Page 2 (repeat header to ensure repeats are preserved)
    doc.add_text(
        label=DocItemLabel.PAGE_HEADER,
        text="Proceedings 2026",
        prov=_prov(2, top=36.0),
        content_layer=ContentLayer.FURNITURE,
    )
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="Body content on page two.",
        prov=_prov(2, top=120.0, width=240.0),
        content_layer=ContentLayer.BODY,
    )
    doc.add_text(
        label=DocItemLabel.PAGE_FOOTER,
        text="2",
        prov=_prov(2, top=810.0, width=24.0),
        content_layer=ContentLayer.FURNITURE,
    )

    md = _render_markdown_with_page_sections(
        document=doc,
        image_mode=ImageRefMode.PLACEHOLDER,
        image_placeholder="<!-- image -->",
    )

    assert "[[[PAGE:1|HEADER|START]]]" in md
    assert "[[[PAGE:1|HEADER|END]]]" in md
    assert "[[[PAGE:1|BODY|START]]]" in md
    assert "[[[PAGE:1|BODY|END]]]" in md
    assert "[[[PAGE:1|FOOTER|START]]]" in md
    assert "[[[PAGE:1|FOOTER|END]]]" in md
    assert "[[[PAGE:2|HEADER|START]]]" in md
    assert "[[[PAGE:2|BODY|START]]]" in md
    assert "[[[PAGE:2|FOOTER|END]]]" in md
    assert md.count("Proceedings 2026") == 2
    assert "Body content on page one." in md
    assert "Body content on page two." in md
    assert md.count("--- Page Break ---") == 1
    assert "###" not in md


def test_page_sections_emit_explicit_empty_markers() -> None:
    doc = DoclingDocument(name="empty-furniture")
    doc.add_page(page_no=1, size=Size(width=595, height=842))
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="Only body text",
        prov=_prov(1, top=200.0, width=180.0),
        content_layer=ContentLayer.BODY,
    )

    md = _render_markdown_with_page_sections(
        document=doc,
        image_mode=ImageRefMode.PLACEHOLDER,
        image_placeholder="<!-- image -->",
    )

    assert "[[[PAGE:1|HEADER|START]]]" in md
    assert "[[[PAGE:1|HEADER|EMPTY]]]" in md
    assert "[[[PAGE:1|HEADER|END]]]" in md
    assert "[[[PAGE:1|BODY|START]]]" in md
    assert "[[[PAGE:1|BODY|END]]]" in md
    assert "[[[PAGE:1|FOOTER|START]]]" in md
    assert "[[[PAGE:1|FOOTER|EMPTY]]]" in md
    assert "[[[PAGE:1|FOOTER|END]]]" in md
    assert "Only body text" in md
