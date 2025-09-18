import json
from .category_key_registry import get_required_keys

CARRIER_DEFAULT_LIKE_KEYS = [
    "Member Website",
    "Out of Network Explanation",
    "Customer Service Phone Number"
]

SPECIAL_PROMPT_INSTRUCTIONS = {
    "dental": """
**EXCEPTION FOR UNITEDHEALTHCARE PLANS:**
- If the plan is identified as "UnitedHealthcare" (by carrier name or branding in the PDF), for the fields "Single Deductible" and "Family Deductible" (both In-Network and Out-of-Network), you MAY copy these values from the matched sample JSON instead of the target PDF, to ensure correct mapping. This exception applies only to these deductible fields for UnitedHealthcare plans.

---

**CRITICAL FIELD EXTRACTION FOR SPECIFIC BENEFITS:**
- For the following fields: "Cleanings", "Exams", "X-Rays", "Sealants", "Fillings", "Simple Extractions", "Root Canal", "Periodontal Gum Disease", "Oral Surgery", "Crowns", "Dentures", "Bridges", "Implants", "Orthodontia" (both In-Network and Out-of-Network), you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
- If these fields are not present in the target PDF, return an empty string ("").
""",
    "vision": """
**CRITICAL FIELD EXTRACTION FOR VISION BENEFITS:**
- For the following fields: "Eye Exam", "Single Vision Lens", "Lined Bi-Focal Lens", "Lined Tri-Focal Lens", "Lenticular Lens", "Contact Lens Allowance", "Frame Allowance", you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
- If these fields are not present in the target PDF, return an empty string ("").
""",
    # Add more categories as needed...
}

def filter_to_required_keys(predicted: dict, required_keys: list):
    """Retain only required keys, fill blanks if missing."""
    return {k: predicted.get(k, "") for k in required_keys}

def fill_from_matched_sample(result_json: dict, matched_sample_json: dict):
    """Fill default-likely fields from matched sample if missing."""
    for key in CARRIER_DEFAULT_LIKE_KEYS:
        if not result_json.get(key):  # empty or missing
            result_json[key] = matched_sample_json.get(key, "")
    return result_json

def replace_nulls(obj):
    if isinstance(obj, dict):
        return {k: replace_nulls(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [replace_nulls(x) for x in obj]
    elif obj is None:
        return ""
    else:
        return obj

def get_system_prompt(category, required_keys):
    keys_str = "\n".join([f'- "{k}"' for k in required_keys])
    category = category.lower()
    special_instructions = SPECIAL_PROMPT_INSTRUCTIONS.get(category, "")

    system_prompt = f"""
You are a highly accurate insurance PDF-to-JSON converter.

**Your task:** Extract specific insurance benefits and details, using ONLY the target PDF text provided, into the JSON fields listed below.

---

**CRITICAL EXTRACTION RULES:**
- For every field (except "Member Website", "Out of Network Explanation", "Customer Service Phone Number"), extract values *only and exactly from the target PDF text*. NEVER use, infer, or copy values from sample pairs for these fields.
- If a field is not present in the target PDF, return an empty string ("").
- ONLY for "Member Website", "Out of Network Explanation", and "Customer Service Phone Number", you may copy a sample value as fallback if missing from the target.
- Never omit any fields from the output JSON.
- If multiple prices or values are listed for a benefit field, ALWAYS select the highest price or percentage value.**

---

{special_instructions}

---

**Sample pairs:** Are provided ONLY to help you learn the possible ways insurance information is presented and mapped. NEVER use sample values in the target output (except the fallback fields above and the UnitedHealthcare deductible exception).

---

**Field-matching and mapping instructions:**

- **Direct table mapping:** If PDF has a simple table or list mapping benefit fields (e.g., "Crowns In-Network"), extract those values directly.
- **Grouped or classified layouts (e.g., "Type A/B/C", "Class I/II/III", "Type 1/2/3", "Preventive/Basic/Major", etc.):**
    - You must determine each benefit's group/class only from the target PDF text itself (headings, tables, legends, or explicit mapping in that document).
    - Never use or borrow group/class assignments from any sample pair. If the target PDF does not explicitly show which group/class a benefit belongs to, set its value to "".
    - Once the benefit's group/class is identified in the target PDF, use that same PDF's coverage values for the group/class (e.g., "Type B is 90%") and assign them.
    - If the target PDF uses different labels (e.g., "Preventive/Basic/Major" instead of "Type A/B/C"), follow those exactly from the PDF. Do not assume mappings from the samples.

- **Synonyms and variations:** Recognize that "In-Network"/"Out-of-Network" may be labeled as "Tier 1/2", "PPO/Premier", "Network/Non-Network", "Preferred/Non-Preferred", etc. Map accordingly, using current PDF context.

- When a field is neither directly mapped in a table nor present in any grouping, set its value to "".

---

**Sample Pair Usage Rules:**
- Carefully review all provided sample pairs. Identify how fields may be mapped differently (direct, grouped, multistep).
- Use samples only as logic references for possible extraction or mapping methods, never as content sources.
- Generalize mapping logic from all samples, not just the nearest one, but *always* apply it to the target PDF's specific presentation and wording.

---

**For all fields:**  
Extract and output ONLY these fields (no extras):

{keys_str}

---

**Output:** Output only the completed JSON object with all fields above, and nothing else.

"""
    return system_prompt

def ask_llm_mapping_logic(
    llm, # LLM model
    sample_pairs, # List of tuples: (sample_pdf_text, sample_json)
    dest_pdf_text: str,
    category: str
) -> dict:
    required_keys = get_required_keys(category)
    system_prompt = get_system_prompt(category, required_keys)

    user_prompt = ""
    for i, (sample_pdf_text, sample_json) in enumerate(sample_pairs):
        user_prompt += f"SAMPLE PDF TEXT #{i+1}:\n-----\n{sample_pdf_text}\n-----\n"
        user_prompt += f"SAMPLE PLAN JSON #{i+1}:\n{json.dumps(sample_json, indent=2)}\n-----\n"

    user_prompt += f"TARGET PDF TEXT:\n-----\n{dest_pdf_text}\n-----\n"
    user_prompt += "Output the target's JSON only:"


    result_json = llm.chat(system_prompt, user_prompt)
    try:
        parsed = json.loads(result_json)
    except Exception:
        # Sometimes LLM adds markdown code fencing
        result_json = result_json[result_json.find("{"):result_json.rfind("}")+1]
        parsed = json.loads(result_json)

    print(f"parsed is \n: {parsed}")
    return parsed

CARRIER_DEFAULT_LIKE_KEYS = [
    "Member Website",
    "Out of Network Explanation",
    "Customer Service Phone Number"
]

def filter_to_required_keys(predicted: dict, required_keys: list):
    """Retain only required keys, fill blanks if missing."""
    return {k: predicted.get(k, "") for k in required_keys}

def fill_from_matched_sample(result_json: dict, matched_sample_json: dict):
    """Fill default-likely fields from matched sample if missing."""
    for key in CARRIER_DEFAULT_LIKE_KEYS:
        if not result_json.get(key):  # empty or missing
            result_json[key] = matched_sample_json.get(key, "")
    return result_json

def replace_nulls(obj):
    if isinstance(obj, dict):
        return {k: replace_nulls(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [replace_nulls(x) for x in obj]
    elif obj is None:
        return ""
    else:
        return obj