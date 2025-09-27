import os
import re
from pathlib import Path

# Root folder (search recursively for PDFs and DOCXs)
ROOT_FOLDER = "sample_data/9. Health/HEALTH PDF-WORD PAIRS/UHC"

# Regex to capture the 4-char code after "benefit_summary_"
PDF_PATTERN = re.compile(r"benefit_summary_([A-Za-z0-9]{4})", re.IGNORECASE)

def rename_docx_to_match_pdf(root_folder):
    pdf_map = {}

    # Step 1: Walk through all files and collect PDFs
    for root, _, files in os.walk(root_folder):
        for file in files:
            if file.lower().endswith(".pdf"):
                match = PDF_PATTERN.search(file)
                if match:
                    code = match.group(1)
                    pdf_map[code] = os.path.join(root, file)

    # Step 2: Walk again and check docx files
    for root, _, files in os.walk(root_folder):
        for file in files:
            if file.lower().endswith(".docx") and not file.startswith("~$"):  # skip temp files
                for code, pdf_path in pdf_map.items():
                    if code in file:  # match found
                        pdf_name = Path(pdf_path).stem  # base PDF name (no extension)
                        new_name = f"{pdf_name}.docx"
                        old_path = os.path.join(root, file)
                        new_path = os.path.join(root, new_name)

                        # Rename only if different
                        if old_path != new_path:
                            os.rename(old_path, new_path)
                            print(f"✅ Renamed: {old_path} → {new_path}")
                        break  # stop after first match

rename_docx_to_match_pdf(ROOT_FOLDER)
