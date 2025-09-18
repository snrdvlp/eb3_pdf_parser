import os
import json
from docx import Document
from pathlib import Path

# Source folder with DOCX files (may contain subfolders)
DOCX_FOLDER = "sample_data/7. Critical Illness_all"
# Destination folder for JSON files
JSON_FOLDER = "sample_data/7. Critical Illness_all"

os.makedirs(JSON_FOLDER, exist_ok=True)

def parse_doc_to_dict(doc_path):
    """Convert DOCX paragraphs with 'key: value' format into a dictionary."""

    # Skip Word lock/temp files
    if os.path.basename(doc_path).startswith("~$"):
        print(f"Skipping lock file: {doc_path}")
        return None
        
    doc = Document(doc_path)
    data = {}
    for para in doc.paragraphs:
        line = para.text.strip()
        if not line:
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    return data

# Walk through DOCX_FOLDER recursively
for root, dirs, files in os.walk(DOCX_FOLDER):
    for filename in files:
        if filename.endswith(".docx"):
            doc_path = os.path.join(root, filename)

            # Parse DOCX to dictionary
            data = parse_doc_to_dict(doc_path)

            # Determine relative path to preserve folder structure
            rel_path = os.path.relpath(root, DOCX_FOLDER)
            target_folder = os.path.join(JSON_FOLDER, rel_path)
            os.makedirs(target_folder, exist_ok=True)

            # Save JSON
            base_name = os.path.splitext(filename)[0]
            json_path = os.path.join(target_folder, f"{base_name}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            print(f"[✔] Converted {doc_path} → {json_path}")
