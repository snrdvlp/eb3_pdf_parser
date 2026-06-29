import io
import pdfplumber
import fitz  # PyMuPDF
import time
import re
import pytesseract
from PIL import Image

def decode_cid_codes(text: str) -> str:
    """
    Decode CID (Character ID) codes to their Unicode equivalents.
    CID codes like (cid:84)(cid:104)(cid:101) represent characters in embedded fonts.
    """
    def cid_to_char(match):
        cid_num = int(match.group(1))
        # Common CID mappings for Latin characters
        # CID 32-126 maps to ASCII 32-126 (space to ~)
        if 32 <= cid_num <= 126:
            return chr(cid_num)
        # Additional common mappings
        cid_mappings = {
            160: ' ',   # non-breaking space
            173: '-',   # soft hyphen
            8211: '–',  # en dash
            8212: '—',  # em dash
            8216: ''',  # left single quotation mark
            8217: ''',  # right single quotation mark
            8220: '"',  # left double quotation mark
            8221: '"',  # right double quotation mark
        }
        return cid_mappings.get(cid_num, f'[CID:{cid_num}]')
    
    # Replace (cid:number) patterns
    return re.sub(r'\(cid:(\d+)\)', cid_to_char, text)

def clean_pdf_text(raw_text: str) -> str:
    """
    Clean extracted PDF text for LLM prompts.
    - Decodes CID codes to Unicode characters
    - Removes noisy OCR artifacts
    - Normalizes whitespace
    - Keeps Markdown tables and headings
    """
    # First decode CID codes
    cleaned = decode_cid_codes(raw_text)
    
    # Remove weird symbols / artifacts inside {}
    cleaned = re.sub(r"\{[^}]*\}", "", cleaned)

    # Remove random non-alphanumeric garbage tokens (like OCR errors)
    cleaned = re.sub(r"[^\x00-\x7F]+", " ", cleaned)  # remove non-ASCII
    cleaned = re.sub(r"\s{2,}", " ", cleaned)  # collapse multiple spaces

    # Fix line breaks around tables/headings
    cleaned = re.sub(r"\n{2,}", "\n\n", cleaned)  # collapse blank lines

    # Strip leading/trailing whitespace
    return cleaned.strip()

def pdf_to_text(pdf_bytes: bytes) -> str:
    """
    Detect PDF type and extract text accordingly.
    Returns: text string
    """
    start_time = time.perf_counter()
    
    # First, try to detect PDF type
    pdf_type = detect_pdf_type(pdf_bytes)
    
    print(f"Detected PDF type: {pdf_type}")
    
    # Extract text based on detected type
    if pdf_type == 'image':
        text = pdf_to_text_ocr(pdf_bytes)
    else:
        try:
            text = pdf_to_text_with_tables(pdf_bytes)
        except Exception as e:
            print(f"Text extraction failed: {e}, falling back to OCR")
            text = pdf_to_text_ocr(pdf_bytes)
    
    elapsed_time = time.perf_counter() - start_time
    print(f"Total processing time: {elapsed_time:.2f} seconds")
    print(f"PDF type: {pdf_type}")
    
    return text
def detect_pdf_type(pdf_bytes: bytes) -> str:
    """
    Hybrid approach: check text presence, quality, and fallback to OCR if needed.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) == 0:
        return 'image'
    
    # Check first 3 pages for text presence and quality
    text_pages = 0
    high_quality_pages = 0
    pages_to_check = min(3, len(doc))
    
    for page_num in range(pages_to_check):
        page = doc[page_num]
        text = page.get_text().strip()

        if len(text) > 50:  # Has substantial text
            text_pages += 1
            # Check text quality
            words = text.split()
            if len(words) > 10:  # Has enough words
                # Check for common OCR artifacts
                ocr_artifacts = sum(1 for word in words if len(word) == 1 and not word.isalnum())
                artifact_ratio = ocr_artifacts / len(words) if words else 0
                
                # If less than 20% artifacts, consider high quality
                if artifact_ratio < 0.2:
                    high_quality_pages += 1

    doc.close()
    # Decision logic
    if high_quality_pages >= 2:  # At least 2 high-quality text pages
        return 'text'
    elif text_pages >= 2:  # At least 2 pages with text (but lower quality)
        return 'text'  # Might be poor quality text, but still text-based
    else:
        return 'image'

def pdf_to_text_with_tables(pdf_bytes: bytes, max_pages: int = 13) -> str:
    """
    Convert PDF (bytes) into a Markdown string, preserving text structure and tables.
    Only processes up to `max_pages` pages.
    """
    markdown_output = ""

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    plumber_pdf = pdfplumber.open(io.BytesIO(pdf_bytes))

    total_pages = min(len(doc), max_pages)

    def is_section_header(row):
        # A header has exactly one non-empty cell, all uppercase, and not a number
        non_empty = [cell for cell in row if cell and str(cell).strip()]
        return (
            len(non_empty) == 1 and
            isinstance(non_empty[0], str) and
            non_empty[0].isupper() and
            not any(char.isdigit() for char in non_empty[0])
        )

    for page_num in range(total_pages):
        page = doc[page_num]
        markdown_output += f"\n\n## Page {page_num + 1}\n\n"

        plumber_page = plumber_pdf.pages[page_num]
        table_settings = {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "intersection_tolerance": 8,
        }
        tables = plumber_page.extract_tables(table_settings=table_settings)
        for table in tables:
            if not table:
                continue

            # Detect label column index for grouping headers
            def label_column_index(row):
                for i, cell in enumerate(row):
                    if cell and not any(char.isdigit() for char in str(cell)) and "%" not in str(cell) and "$" not in str(cell):
                        return i
                return None

            label_indices = [label_column_index(row) for row in table[1:6] if label_column_index(row) is not None]
            common_label_idx = max(set(label_indices), key=label_indices.count) if label_indices else 0

            filled_table = [table[0]]  # header row
            prev_row = table[0]

            for row in table[1:]:
                if is_section_header(row):  # Check for section header
                    # Add section header as a new table row with only that cell filled (all others blank)
                    hdr_idx = [i for i, c in enumerate(row) if c and str(c).strip()]
                    section_row = ['' for _ in row]
                    if hdr_idx:
                        section_row[hdr_idx[0]] = str(row[hdr_idx[0]])
                    filled_table.append(section_row)
                    prev_row = row  # Don't use header row for filling down data
                    continue

                curr_label_idx = label_column_index(row)
                is_header = curr_label_idx != common_label_idx
                if is_header:
                    prev_row = row

                filled_row = []
                for i, cell in enumerate(row):
                    def is_numeric(val):
                        if not val:
                            return False
                        val = str(val).strip()
                        return "%" in val or "$" in val or val.replace('.', '', 1).isdigit()
                    if cell not in [None, ""] and is_numeric(cell):
                        filled_row.append(cell)
                    elif cell in [None, ""] and is_numeric(prev_row[i]) and not is_header and not is_section_header(prev_row):
                        filled_row.append(prev_row[i])
                    else:
                        filled_row.append(cell)
                filled_table.append(filled_row)
                if not is_header:
                    prev_row = filled_row

            # Merge continuation rows back into the previous logical row.
            # SBC tables often wrap a single cell across multiple visual lines,
            # and pdfplumber can emit those wrapped lines as extra rows with empty
            # label cells. This merge step reconstructs the intended row structure.
            def _merge_cell(a, b):
                a = "" if a is None else str(a).strip()
                b = "" if b is None else str(b).strip()
                if not a:
                    return b
                if not b:
                    return a
                # Avoid duplicating identical fragments
                if b in a:
                    return a
                return a + " " + b

            def _is_effective_empty(x):
                return x is None or str(x).strip() == ""

            merged_rows = [filled_table[0]]
            for row in filled_table[1:]:
                # Always keep explicit section header rows as their own rows
                if is_section_header(row):
                    merged_rows.append(row)
                    continue

                # Determine if this looks like a continuation line:
                # - label cell is empty (or very short)
                # - and there is some content elsewhere (typically in network/out-of-network/limitations columns)
                label_cell = row[common_label_idx] if common_label_idx < len(row) else ""
                non_empty_cells = sum(0 if _is_effective_empty(c) else 1 for c in row)
                looks_like_continuation = _is_effective_empty(label_cell) and non_empty_cells > 0

                if looks_like_continuation and len(merged_rows) > 1:
                    prev = merged_rows[-1]
                    # Merge cell-by-cell to preserve column alignment
                    new_prev = []
                    for i in range(max(len(prev), len(row))):
                        a = prev[i] if i < len(prev) else ""
                        b = row[i] if i < len(row) else ""
                        # Only merge into cells where previous is empty or row has extra text.
                        # This prevents overwriting stable numeric values.
                        if _is_effective_empty(a):
                            new_prev.append(b)
                        else:
                            # If the continuation row has text for this column, append it.
                            new_prev.append(_merge_cell(a, b) if not _is_effective_empty(b) else a)
                    merged_rows[-1] = new_prev
                else:
                    merged_rows.append(row)

            filled_table = merged_rows

            # Render as Markdown table
            markdown_output += f"\n\n### Table (Page {page_num + 1})\n\n"
            header = filled_table[0]
            markdown_output += "| " + " | ".join(str(h or "") for h in header) + " |\n"
            markdown_output += "| " + " | ".join("---" for _ in header) + " |\n"
            for row in filled_table[1:]:
                markdown_output += "| " + " | ".join(str(cell or "") for cell in row) + " |\n"
            markdown_output += "\n"

        # --- Step 2: Extract text blocks ---
        blocks = page.get_text("blocks")
        for block in blocks:
            text = block[4].strip()
            if not text:
                continue
            if len(text.split()) <= 8 and text.isupper():
                markdown_output += f"### {text}\n\n"
            else:
                markdown_output += text + "\n\n"

    plumber_pdf.close()
    return clean_pdf_text(markdown_output.strip())

def pdf_to_text_ocr(pdf_bytes: bytes, max_pages: int = 13) -> str:
    """
    Convert image-based PDF to text using OCR with performance optimizations.
    Input: pdf_bytes (from await pdf_file.read())
    Output: text string
    """
    start_time = time.perf_counter()
    
    # Open PDF document
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    extracted_text = ""
    total_pages = min(len(doc), max_pages)
    
    print(f"Processing {total_pages} pages with OCR...")
    
    for page_num in range(total_pages):
        page_start = time.perf_counter()
        page = doc[page_num]
        
        # Convert page to image with optimal settings
        pix = page.get_pixmap(dpi=300, alpha=False)  # Higher DPI, no alpha channel
        
        # Convert pixmap to PIL Image
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        
        # Preprocess image for better OCR (optional)
        # Convert to grayscale for better OCR accuracy
        if img.mode != 'L':
            img = img.convert('L')
        
        # Perform OCR with custom configuration
        custom_config = r'--oem 3 --psm 6'  # OCR Engine Mode 3, Page Segmentation Mode 6
        page_text = pytesseract.image_to_string(img, config=custom_config, lang='eng')
        
        # Add page separator
        extracted_text += f"\n\n## Page {page_num + 1}\n\n"
        extracted_text += page_text
        
        page_time = time.perf_counter() - page_start
        print(f"Page {page_num + 1} processed in {page_time:.2f} seconds")
    
    doc.close()
    
    # Clean the extracted text using your existing function
    cleaned_text = clean_pdf_text(extracted_text)
    
    # Print total elapsed time
    total_time = time.perf_counter() - start_time
    print(f"OCR processing completed in {total_time:.2f} seconds")
    print(f"Average time per page: {total_time/total_pages:.2f} seconds")
    
    return cleaned_text
