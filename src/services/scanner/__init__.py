import logging
import os

# DocTR opens a ThreadPool for every batch. On Windows each of those threads leaves its torch
# worker threads behind for good (~200 per page): a 300-page PDF reached 159,379 threads and
# 21 GB and took the web server down. Single-threaded preprocessing does not leak.
os.environ.setdefault('DOCTR_MULTIPROCESSING_DISABLE', 'TRUE')

logger = logging.getLogger(__name__)

SCANNER_AVAILABLE = False

try:
    import cv2
    import langdetect
    import numpy as np
    import easyocr
    from doctr.io import DocumentFile
    import ultralytics
    SCANNER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Scanner dependencies missing: {e}. Scanner module will be disabled.")
    SCANNER_AVAILABLE = False
