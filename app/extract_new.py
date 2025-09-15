import io
import fitz  # PyMuPDF
import pdfplumber
import camelot
import tempfile

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def has_text_layer(pdf_bytes: bytes) -> bool:
    """
    Check if the PDF has a real text layer (not just scanned images).
    Returns True if any page contains extractable text.
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            if page.get_text("text").strip():
                return True
    return False

def table_to_string(table):
    """
    Convert a table (list of rows) into a clean text block.
    Each row is joined with ' | ' and rows are joined by newline.
    """
    rows = []
    for row in table:
        clean_row = [cell.strip().replace("\n", " ") if cell else "" for cell in row]
        rows.append(" | ".join(clean_row))
    return "\n".join(rows)

def extract_text_and_tables_as_string(pdf_bytes: bytes):
    """
    Extract normal text (PyMuPDF) and tables (pdfplumber + Camelot) from PDFs with a text layer.
    Returns (text_string, tables_string).
    """
    text_output = []
    tables_output = []

    # --- Free-form text (PyMuPDF) ---
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            page_text = page.get_text("text")
            if page_text.strip():
                text_output.append(page_text)

    # --- Tables with pdfplumber ---
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if table:
                    tables_output.append(table_to_string(table))

    # --- Camelot for complex tables ---
    try:
        # Camelot requires a file, so write bytes to a temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            tmp.flush()
            # 'stream' flavor is good for tables without explicit borders
            tables = camelot.read_pdf(tmp.name, pages="all", flavor="stream", edge_tol=500)
            for t in tables:
                tables_output.append(table_to_string(t.data))
    except Exception:
        pass

    # Merge results
    text_string = "\n\n".join(text_output)
    tables_string = "\n\n---TABLE---\n\n".join(tables_output)
    return text_string, tables_string

def ocr_pdf(pdf_bytes: bytes):
    """
    OCR fallback for scanned PDFs using pytesseract.
    Lazy-imports pytesseract + Pillow to avoid mandatory dependency.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise RuntimeError(
            "OCR required but pytesseract or Pillow is not installed. "
            "Install with: pip install pytesseract Pillow"
        )

    text = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text += pytesseract.image_to_string(img) + "\n"
    return text

# ------------------------------------------------------------
# Main extractor
# ------------------------------------------------------------

def extract_pdf_to_string(pdf_bytes: bytes):
    """
    Extract text + tables from PDFs.
    Returns a dictionary:
        - type: "text" if PDF has text layer, "ocr" otherwise
        - content: combined text + tables
    """
    if has_text_layer(pdf_bytes):
        text, tables = extract_text_and_tables_as_string(pdf_bytes)
        final_content = ""
        if tables.strip():
            final_content += "\n\n[TABLES]\n" + tables
        final_content += text
        return {"type": "text", "content": final_content}
    else:
        text = ocr_pdf(pdf_bytes)
        return {"type": "ocr", "content": text}
