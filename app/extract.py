import io
import pdfplumber
import fitz  # PyMuPDF

def pdf_to_text(pdf_bytes: bytes) -> str:
    return pdf_to_text_with_tables(pdf_bytes)

def pdf_to_text_with_tables(pdf_bytes: bytes) -> str:
    """
    Convert PDF (bytes) into a Markdown string, preserving text structure and tables.
    - Tables appear before text on each page.
    - Headings are auto-detected (short UPPERCASE text).
    - Paragraphs are preserved.
    """
    markdown_output = ""

    # Load with both pdfplumber and PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    plumber_pdf = pdfplumber.open(io.BytesIO(pdf_bytes))

    for page_num, page in enumerate(doc, start=1):
        markdown_output += f"\n\n## Page {page_num}\n\n"

        # --- Step 1: Extract tables first ---
        plumber_page = plumber_pdf.pages[page_num - 1]
        table_settings = {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "intersection_tolerance": 8,
        }
        tables = plumber_page.extract_tables(table_settings=table_settings)
        for table in tables:
            if not table:
                continue

            # Detect the main label column by finding the first non-empty, non-numeric cell in each row
            def label_column_index(row):
                for i, cell in enumerate(row):
                    if cell and not any(char.isdigit() for char in str(cell)) and "%" not in str(cell) and "$" not in str(cell):
                        return i
                return None

            # Find the most common label column index in the first N data rows (skip header)
            label_indices = []
            for row in table[1:6]:  # adjust range as needed
                idx = label_column_index(row)
                if idx is not None:
                    label_indices.append(idx)
            if label_indices:
                common_label_idx = max(set(label_indices), key=label_indices.count)
            else:
                common_label_idx = 0  # fallback

            filled_table = [table[0]]  # header
            prev_row = table[0]
            for row in table[1:]:
                curr_label_idx = label_column_index(row)
                # If label column index changes, treat as header
                is_header = curr_label_idx != common_label_idx
                if is_header:
                    prev_row = row  # Reset autofill at header
                filled_row = []
                for i, cell in enumerate(row):
                    def is_numeric(val):
                        if not val:
                            return False
                        val = str(val).strip()
                        return (
                            "%" in val or
                            "$" in val or
                            val.replace('.', '', 1).isdigit()
                        )
                    if cell not in [None, ""] and is_numeric(cell):
                        filled_row.append(cell)
                    elif cell in [None, ""] and is_numeric(prev_row[i]) and not is_header:
                        filled_row.append(prev_row[i])
                    else:
                        filled_row.append(cell)
                filled_table.append(filled_row)
                # Only update prev_row if current row is not a header
                if not is_header:
                    prev_row = filled_row

            markdown_output += f"\n\n### Table (Page {page_num})\n\n"
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
    return markdown_output.strip()