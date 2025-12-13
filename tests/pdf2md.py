# Configurations
import os
import gc
import random
import signal
import warnings
import logging
from io import BytesIO
from time import sleep
from datetime import datetime

from dotenv import load_dotenv
import pandas as pd
import torch
from joblib import Parallel, delayed
from tqdm import tqdm
from pyzotero import zotero

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    PdfPipelineOptions,
    TableFormerMode,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.base import ImageRefMode
from docling_core.types.io import DocumentStream

load_dotenv()

NJOBS = 12
ZOTERO_GROUP_ID = os.getenv("ZOTERO_GROUP_ID")
ZOTERO_API_KEY = os.getenv("ZOTERO_API_KEY")
DO_PICTURE_DESCRIPTION = False
FORCE_FULL_PAGE_OCR = False
IMAGE_RESOLUTION_SCALE = 4

# Configure logging to file and console
file_handler = logging.FileHandler("../output/pdf2txt.log")
file_handler.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[file_handler, console_handler],
)

# Silence HTTP request logs from dependencies
for name in (
    "urllib3",
    "urllib3.connectionpool",
    "requests",
    "pyzotero",
    "pyzotero.zotero",
    "httpx",
    "httpcore",
):
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.WARNING)
    logger.propagate = False


def get_pipeline_options(
    force_full_page_ocr: bool,
    do_picture_description: bool,
    image_resolution_scale: int,
    device: AcceleratorDevice = AcceleratorDevice.AUTO,
    num_threads: int = 4,
) -> PdfPipelineOptions:
    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = True
    pipeline_options.do_picture_description = do_picture_description
    pipeline_options.do_formula_enrichment = True
    pipeline_options.do_code_enrichment = True
    pipeline_options.ocr_options.force_full_page_ocr = force_full_page_ocr
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
    pipeline_options.table_structure_options.do_cell_matching = True
    pipeline_options.images_scale = image_resolution_scale

    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=num_threads, device=device
    )
    return pipeline_options


def pdf2md(
    pdf_file_key: str,
    download_timeout: int = 5 * 60,
    conversion_timeout: int = 10 * 60,
    use_multi_gpu: bool = True,
    num_gpus_available: int = 0,
    job_index: int = 0,
    force_full_page_ocr: bool = FORCE_FULL_PAGE_OCR,
    do_picture_description: bool = DO_PICTURE_DESCRIPTION,
    image_resolution_scale: int = IMAGE_RESOLUTION_SCALE,
) -> dict:
    """
    Downloads a PDF from Zotero, converts it to Markdown, and counts the words.

    Args:
        pdf_file_key (str): The key of the PDF item in Zotero.
        download_timeout (int): Timeout for downloading the PDF in seconds.
        conversion_timeout (int): Timeout for converting the PDF in seconds.
        use_multi_gpu (bool): Whether to distribute processing across available GPUs.
        num_gpus_available (int): Total number of GPUs available in the system.
        job_index (int): Index of the current job for GPU distribution.

    Returns:
        dict: A dictionary containing the file key, word count, and extracted text.
    """
    # Initialize client within the worker process for parallel safety
    worker_zotero = zotero.Zotero(ZOTERO_GROUP_ID, "group", ZOTERO_API_KEY)
    pdf_md = None
    word_count = None
    confidence_scores = None

    # Placeholders for cleanup
    converter = None
    doc_stream = None
    result = None

    def handler(signum, frame):
        raise TimeoutError("Processing timed out")

    try:
        sleep(random.uniform(0.5, 1.5))

        # Set signal handler for timeouts
        signal.signal(signal.SIGALRM, handler)

        # Download with timeout
        try:
            signal.alarm(download_timeout)
            pdf_bytes = worker_zotero.file(pdf_file_key)
        finally:
            signal.alarm(0)

        doc_stream = DocumentStream(
            name=f"{pdf_file_key}.pdf", stream=BytesIO(pdf_bytes)
        )

        # GPU Handling
        device_selection = AcceleratorDevice.AUTO
        if use_multi_gpu and num_gpus_available > 0:
            # Set CUDA_VISIBLE_DEVICES to restrict this process to a single GPU
            gpu_idx = job_index % num_gpus_available
            os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_idx)
            device_selection = AcceleratorDevice.CUDA

        pipeline_options = get_pipeline_options(
            force_full_page_ocr=force_full_page_ocr,
            do_picture_description=do_picture_description,
            image_resolution_scale=image_resolution_scale,
            device=device_selection,
        )

        # Convert with timeout
        try:
            signal.alarm(conversion_timeout)

            # Initialize converter inside timeout block as it might load models
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )

            result = converter.convert(doc_stream)
            # https://docling-project.github.io/docling/reference/docling_document/#docling_core.types.doc.DoclingDocument.export_to_markdown
            pdf_md = result.document.export_to_markdown(
                image_mode=ImageRefMode.EMBEDDED,
                page_break_placeholder="\\n\\n--- Page Break ---\\n\\n",
            )

            if result.confidence:
                confidence_scores = {
                    "parse_score": result.confidence.parse_score,
                    "layout_score": result.confidence.layout_score,
                    "table_score": result.confidence.table_score,
                    "ocr_score": result.confidence.ocr_score,
                }
        finally:
            # Disable the alarm
            signal.alarm(0)

        word_count = len(pdf_md.split())
        msg = f"SUCCESS: File key {pdf_file_key} | Words: {word_count} | Stats: {confidence_scores}"
        logging.info(msg)
    except TimeoutError:
        pdf_md = "Processing skipped due to timeout."
        msg = f"FAILURE: Timeout processing file key {pdf_file_key}"
        logging.error(msg)
    except Exception as e:
        pdf_md = str(e)
        msg = f"FAILURE: Error processing file key {pdf_file_key}: {e}"
        logging.error(msg)

    # Cleanup GPU memory
    try:
        if converter:
            del converter
        if result:
            del result
        if doc_stream:
            del doc_stream
    except UnboundLocalError:
        pass

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

    return {
        "pdf_file_key": pdf_file_key,
        "word_count": word_count,
        "pdf_md": pdf_md,
        "confidence_scores": confidence_scores,
    }


if __name__ == "__main__":
    # Suppress warnings early
    warnings.filterwarnings("ignore")
    warnings.simplefilter(action="ignore", category=FutureWarning)

    # Load and filter item data
    logging.info("Loading and filtering item data...")
    df_all_items = pd.read_pickle("../data/df_all_items.pkl.gzip", compression="gzip")
    df_all_items_pdf = df_all_items[
        df_all_items["data.contentType"] == "application/pdf"
    ]
    logging.info("Data loading complete.")

    pdf_file_keys = df_all_items_pdf["key"].tolist()
    logging.info(f"Found {len(pdf_file_keys)} PDF files to process.")

    # Warmup: Initialize model in main process (using CPU) to ensure artifacts are downloaded
    logging.info("Performing model warmup (CPU)...")
    try:
        warmup_pipeline_options = get_pipeline_options(
            force_full_page_ocr=FORCE_FULL_PAGE_OCR,
            do_picture_description=DO_PICTURE_DESCRIPTION,
            image_resolution_scale=IMAGE_RESOLUTION_SCALE,
            device=AcceleratorDevice.CPU,
            num_threads=1,
        )
        # Instantiate converter to trigger model download/loading
        DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=warmup_pipeline_options
                )
            }
        )
        logging.info("Model warmup complete.")
    except Exception as e:
        logging.warning(f"Model warmup warning: {e}")

    # Get GPU count in main process to pass to workers
    num_gpus_main = 0
    try:
        if torch.cuda.is_available():
            num_gpus_main = torch.cuda.device_count()
        logging.info(f"Detected {num_gpus_main} GPUs available.")
    except Exception as e:
        logging.warning(f"Could not detect GPUs: {e}")

    # Use a with statement for the Parallel object to ensure proper cleanup
    # Using backend="loky" (spawn) to ensure clean process environment for CUDA setting
    logging.info(f"Starting parallel processing with {NJOBS} jobs...")
    with Parallel(n_jobs=NJOBS, backend="loky") as parallel:
        pdf_md = parallel(
            delayed(pdf2md)(key, num_gpus_available=num_gpus_main, job_index=i)
            for i, key in enumerate(tqdm(pdf_file_keys))
        )
    logging.info("Parallel processing finished.")

    df_pdf_md = pd.DataFrame(pdf_md)
    output_path = "../output/df_pdf_md.pkl.gzip"
    logging.info(f"Saving results to {output_path}")
    df_pdf_md.to_pickle(output_path, compression="gzip")
    logging.info("Script finished successfully.")
