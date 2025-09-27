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

def normalize_json_fields(input_path: str):
    """
    Normalize JSON fields to match canonical case-sensitive names.
    Walks through input_path recursively and overwrites files in place.
    """
    for root, _, files in os.walk(input_path):
        for file in files:
            if not file.endswith(".json"):
                continue

            file_path = os.path.join(root, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"❌ Error reading {file_path}: {e}")
                continue

            fixed_data = {}
            for k, v in data.items():
                key_lower = k.lower()
                fixed_key = field_map.get(key_lower, k)  # map if exists, else keep original
                fixed_data[fixed_key] = v

            # Ensure all expected fields exist
            for f in FIELDS:
                if f not in fixed_data:
                    fixed_data[f] = ""

            # Overwrite JSON in place
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(fixed_data, f, indent=2, ensure_ascii=False)

            print(f"✅ Fixed: {file_path}")


# Source folder (recursive)
input_folder = "sample_data/9. Health/"

normalize_json_fields(input_folder)
