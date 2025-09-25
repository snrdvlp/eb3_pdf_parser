import os
import json

# ✅ Canonical field list
FIELDS = [
    "Carrier Name", "Plan Name", 
    "In-Network Single Deductible", "In-Network Family Deductible",
    "Out-of-Network Single Deductible", "Out-of-Network Family Deductible",
    "In-Network Single OOP Max", "In-Network Family OOP Max",
    "Out-of-Network Single OOP Max", "Out-of-Network Family OOP Max",
    "In-Network Coinsurance", "Out-of-Network Coinsurance",
    "In-Network PCP Visit", "Out-of-Network PCP Visit",
    "In-Network Specialist Visit", "Out-of-Network Specialist Visit",
    "In-Network Urgent Care Visit", "Out-of-Network Urgent Care Visit",
    "In-Network ER Visit", "Out-of-Network ER Visit",
    "In-Network Preventive Visit", "Out-of-Network Preventive Visit",
    "In-Network Outpatient Surgery", "Out-of-Network Outpatient Surgery",
    "In-Network Inpatient Surgery", "Out-of-Network Inpatient Surgery",
    "In-Network Newborn Delivery", "Out-of-Network Newborn Delivery",
    "In-Network Major Diagnostics", "Out-of-Network Major Diagnostics",
    "In-Network RX Deductible", "Out-of-Network RX Deductible",
    "In-Network Generic RX", "Out-of-Network Generic RX",
    "In-Network Brand RX", "Out-of-Network Brand RX",
    "In-Network Tier 3 RX", "Out-of-Network Tier 3 RX",
    "In-Network Tier 4 RX", "Out-of-Network Tier 4 RX",
    "In-Network Tier 5 RX", "Out-of-Network Tier 5 RX",
    "In-Network Mail Order RX", "Out-of-Network Mail Order RX",
    "Plan Year", "Deductible Period", "Deductible Explanation",
    "Network Type", "Network Name",
    "Member Website", "Customer Service Phone Number"
]

# Create lowercase mapping for quick lookup
field_map = {f.lower(): f for f in FIELDS}

def normalize_json_fields(input_path: str, output_path: str = None):
    """
    Normalize JSON fields to match canonical case-sensitive names.
    
    Args:
        input_path (str): Path to a folder containing .json files
        output_path (str): Folder to save fixed JSON files (default = overwrite)
    """
    if output_path is None:
        output_path = input_path

    os.makedirs(output_path, exist_ok=True)

    for file in os.listdir(input_path):
        if not file.endswith(".json"):
            continue

        file_path = os.path.join(input_path, file)
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        fixed_data = {}

        for k, v in data.items():
            key_lower = k.lower()
            if key_lower in field_map:
                fixed_key = field_map[key_lower]
            else:
                fixed_key = k  # keep as-is if unknown
            fixed_data[fixed_key] = v

        # Ensure all expected fields exist
        for f in FIELDS:
            if f not in fixed_data:
                fixed_data[f] = ""

        # Save fixed JSON
        out_file = os.path.join(output_path, file)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(fixed_data, f, indent=2, ensure_ascii=False)

        print(f"✅ Fixed: {file} → {out_file}")


# Source folder with DOCX files (may contain subfolders)
input_folder = "sample_data/9. Health_all/"
# Destination folder for JSON files
output_folder = "sample_data/9. Health_all/"

normalize_json_fields(input_folder, output_folder)
