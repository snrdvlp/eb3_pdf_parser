import io
import pdfplumber

def pdf_to_text(pdf_bytes: bytes) -> str:
    return pdf_to_text_with_tables(pdf_bytes)

    # text = ""
    # with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
    #     for page in pdf.pages:
    #         text += page.extract_text() or ""
    #         tables = page.extract_tables()
    #         for table in tables:
    #             for row in table:
    #                 text += "\t".join(str(cell) if cell is not None else "" for cell in row) + "\n"
    # return text

import io
import fitz  # PyMuPDF
import pdfplumber


def pdf_to_text_with_tables(pdf_bytes: bytes) -> str:
    """
    Convert PDF (bytes) into a Markdown string, preserving text structure and tables.
    - Headings are auto-detected (short UPPERCASE text).
    - Paragraphs are preserved.
    - Tables are converted to Markdown tables.
    """
    markdown_output = ""

    # --- Step 1: Extract structured text with PyMuPDF ---
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page_num, page in enumerate(doc, start=1):
        blocks = page.get_text("blocks")  # structured text blocks
        markdown_output += f"\n\n## Page {page_num}\n\n"
        for block in blocks:
            text = block[4].strip()
            if not text:
                continue

            # Heuristic: treat short ALL CAPS text as heading
            if len(text.split()) <= 8 and text.isupper():
                markdown_output += f"### {text}\n\n"
            else:
                markdown_output += text + "\n\n"

    # --- Step 2: Extract tables with pdfplumber ---
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue

                markdown_output += f"\n\n### Table (Page {page_num})\n\n"

                # Markdown header row
                header = table[0]
                markdown_output += "| " + " | ".join(str(h or "") for h in header) + " |\n"
                markdown_output += "| " + " | ".join("---" for _ in header) + " |\n"

                # Markdown data rows
                for row in table[1:]:
                    markdown_output += "| " + " | ".join(str(cell or "") for cell in row) + " |\n"

                markdown_output += "\n"

    return markdown_output.strip()