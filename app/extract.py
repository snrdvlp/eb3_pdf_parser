import io
import pdfplumber
import fitz  # PyMuPDF
import time

def pdf_to_text(pdf_bytes: bytes) -> str:
    return pdf_to_text_with_tables(pdf_bytes)

def pdf_to_text_with_tables(pdf_bytes: bytes, max_pages: int = 10) -> str:
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
    return markdown_output.strip()
