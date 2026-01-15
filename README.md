# zotero-files2md

Export file attachments (for example PDF, Word, HTML, CSV, images) stored in a Zotero library to Markdown using [Docling](https://github.com/docling-project/docling), driven entirely through the official Zotero Web API via [PyZotero](https://github.com/urschrei/pyzotero).

## Features

- Uses Zotero Web API (no direct database access required)
- Authenticates with a Zotero API key (user or group libraries supported)
- Discovers imported file attachments with optional collection/tag filters (collection **keys**)
- Downloads eligible attachments (imported files only) and converts them to Markdown via Docling
- Supports **Multi-GPU** acceleration for document conversion (automatic distribution across available GPUs)
- Configurable Docling pipeline (OCR, picture description, image resolution)
- Organises exported Markdown by parent item and attachment titles
- Supports dry-run mode, overwrite behaviour, chunk-size tuning
- Provides both a CLI and a Python API for programmatic usage

## Requirements

- Python 3.11+
- A Zotero Web API key with at least read access to the target library
- The Zotero library ID (numeric)
- Network access to `https://api.zotero.org`

## Installation

```bash
python -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install .
# or for development
pip install -e .[dev]
```

### Install directly from GitHub

You can install the package without cloning:

```bash
pip install git+https://github.com/ma-ji/zotero-files2md.git#egg=zotero-files2md
```

To upgrade the package to the latest version from GitHub:

```bash
pip install --upgrade git+https://github.com/ma-ji/zotero-files2md.git#egg=zotero-files2md
```

To install a specific tag or branch, append `@ref`, for example:

```bash
pip install git+https://github.com/ma-ji/zotero-files2md.git@v0.1.0#egg=zotero-files2md
pip install git+https://github.com/ma-ji/zotero-files2md.git@main#egg=zotero-files2md
```

You can also install extras (for example, development dependencies) with:

```bash
pip install "git+https://github.com/ma-ji/zotero-files2md.git#egg=zotero-files2md[dev]"
```

## CLI Usage

### Single output directory

```bash
zotero-files2md export \
    ./markdown-output \
    --api-key "$ZOTERO_API_KEY" \
    --library-id 123456 \
    --library-type user \
    --collection ABCD1234 \
    --tag "LLM" \
    --limit 20 \
    --chunk-size 50 \
    --max-workers 8 \
    --overwrite \
    --force-full-page-ocr \
    --do-picture-description \
    --image-resolution-scale 4.0 \
    --image-processing embed \
    --use-multi-gpu \
    --log-level debug
```

### Batch: multiple collections to multiple output directories

Provide one or more `--collection-output COLLECTION_KEY=OUTPUT_DIR` entries:

```bash
zotero-files2md export-batch \
    --collection-output ABCD1234=./markdown-output/collection-a \
    --collection-output EFGH5678=./markdown-output/collection-b \
    --api-key "$ZOTERO_API_KEY" \
    --library-id 123456 \
    --library-type user \
    --tag "LLM" \
    --chunk-size 50 \
    --max-workers 8 \
    --overwrite \
    --log-level info
```

### Arguments

| Argument | Description |
| --- | --- |
| `output_dir` | Directory where Markdown files will be written. Created if missing. |

### Options

| Option | Description | Default |
| --- | --- | --- |
| `--api-key` | Zotero Web API key (prompted if not provided; honours `ZOTERO_API_KEY`). | - |
| `--library-id` | Target Zotero library ID (numeric; honours `ZOTERO_LIBRARY_ID`). | - |
| `--library-type` | Library type (`user` or `group`). | `user` |
| `--collection/-c KEY` | Filter attachments by collection key (repeatable; obtain keys via the Zotero web UI or API). | - |
| `--collection-output/-C KEY=DIR` | Batch mode: export one collection key to a specific output directory (repeatable; use with `export-batch`). | - |
| `--tag/-t NAME` | Filter attachments by tag name (repeatable). | - |
| `--limit N` | Stop after processing `N` attachments. | None |
| `--chunk-size N` | Number of attachments to request per API call. | 100 |
| `--max-workers N` | Upper bound on parallel download/conversion workers (auto-detected if unset; in multi-GPU mode, total workers are capped by `GPU_count * --workers-per-gpu`). | Auto (up to 12) |
| `--workers-per-gpu N` | Maximum worker processes per GPU in multi-GPU mode (lower to reduce OOM risk). | 1 |
| `--overwrite` | Overwrite existing Markdown files instead of skipping. | False |
| `--dry-run` | List target files without downloading attachments or writing Markdown. | False |
| `--force-full-page-ocr` | Force full-page OCR for better quality (slower). | False |
| `--do-picture-description` | Enable GenAI picture description (slower). | False |
| `--image-resolution-scale N` | Image resolution scale for Docling. | 4.0 |
| `--image-processing MODE` | How to handle images in Markdown output (`embed`, `placeholder`, `drop`). | `embed` |
| `--use-multi-gpu` / `--no-use-multi-gpu` | Distribute processing across available GPUs. | True |
| `--log-level LEVEL` | Logging verbosity (`critical`, `error`, `warning`, `info`, `debug`). | `info` |

### Markdown Output Layout

For each processed attachment:

```
output_dir/
└── <parent-item-slug>/
    └── <attachment-title-slug>.md
```

For example:

```
/exports/
└── smith-2023-foundations/
    └── appendix-a-methods.md
```

## Programmatic Usage

```python
from pathlib import Path
from zotero_files2md import export_collections, export_library
from zotero_files2md.settings import ExportSettings

settings = ExportSettings(
    api_key="your-api-key",
    library_id="123456",
    library_type="user",
    output_dir=Path("./markdown-output"),
    collections={"ABCD1234"},
    overwrite=True,
    chunk_size=50,
    max_workers=8,
    use_multi_gpu=True,
    force_full_page_ocr=False,
    do_picture_description=False,
    image_processing="embed",
)

summary = export_library(settings)
print(summary)

# Batch export: multiple collections -> multiple output directories
# Note: ``export_collections`` overrides ``settings.output_dir`` and
# ``settings.collections`` per mapping entry.
batch = export_collections(
    settings,
    {
        "ABCD1234": Path("./markdown-output/collection-a"),
        "EFGH5678": Path("./markdown-output/collection-b"),
    },
)
print(batch)
```

## Development

```bash
pip install -e .[dev]
pytest
```

## Notes & Limitations

- The Zotero Web API only provides access to attachments that are stored in Zotero (`imported_file` / `imported_url`). Linked file attachments (`linked_file`) are skipped automatically.
- Ensure the API key has sufficient permissions for the target library (read at minimum).
- API rate limits apply; adjust `--chunk-size` or insert breaks between runs if necessary.
- If a conversion triggers a CUDA out-of-memory error, the exporter retries that attachment on CPU.
- When running in `--dry-run` mode, attachments are enumerated but files are not downloaded and no Markdown is written.
- When one or more `--collection` keys are supplied, only those collections are queried (via the Zotero `collection_items` endpoint). Provide collection **keys** rather than names; you can copy the key from the Zotero web UI URL.
