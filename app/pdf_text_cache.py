import hashlib
from cachetools import LRUCache
import threading

from .extract import pdf_to_text

PDF_TEXT_CACHE = LRUCache(maxsize=128)
PDF_TEXT_CACHE_LOCK = threading.Lock()

def get_pdf_text_cached(pdf_bytes: bytes) -> str:
    key = hashlib.sha256(pdf_bytes).hexdigest()
    with PDF_TEXT_CACHE_LOCK:
        if key in PDF_TEXT_CACHE:
            return PDF_TEXT_CACHE[key]
    text = pdf_to_text(pdf_bytes)
    with PDF_TEXT_CACHE_LOCK:
        PDF_TEXT_CACHE[key] = text
    return text