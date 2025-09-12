from openai import OpenAI
import json
import os
from dotenv import load_dotenv
from .category_key_registry import get_required_keys

load_dotenv()
OPENAI_GPT_MODEL = "gpt-4.1-mini"
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

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

def ask_gpt_mapping_logic(
    sample_pairs, # List of tuples: (sample_pdf_text, sample_json)
    dest_pdf_text: str,
    category: str
) -> dict:
    required_keys = get_required_keys(category)
    keys_str = "\n".join([f'- "{k}"' for k in required_keys])

    system_prompt = f"""
You are a highly accurate insurance PDF-to-JSON converter.

**Task:** Extract information from target insurance PDF plan summaries into the exact JSON fields listed below.

**CRITICAL EXTRACTION RULES:**
- For every field (except "Member Website", "Out of Network Explanation", "Customer Service Phone Number"), you must extract values *only and exactly from the target PDF text.*
- Return an empty string ("") for any field not present in the target PDF. **Never copy, infer, or re-use values from any sample for these fields.**
- ONLY for "Member Website", "Out of Network Explanation", and "Customer Service Phone Number", if you cannot find the value in the target PDF, you MAY copy it from the samples as a fallback.

**About Sample Pairs:**
- Sample pairs are provided EXCLUSIVELY to help you learn the field-label/row mapping logic. They are not value references for the target.

**Matching/Mappings Guidance:**
- Map similar terms to required fields (e.g. "Tier 1", "Level 1", "PPO", or "In-Area" = "In-Network"; "Tier 2", "Level 2", "Out-of-Area" = "Out-of-Network").
- Always use the *closest relevant* label, header, or section only.
- For all percentage, frequency, dollar amount values, use ONLY what is found directly in the target text/tables.

**For all fields:**
- Extract ONLY these fields:
  {keys_str}
- NEVER copy, reuse, or deduce numerical or factual values from the samples (except in the fallback case specified above).
- If a field does not have a value in the target PDF, set it to "" (never null).
- Never omit any field.

**Special Handling for Grouped Benefit Types (e.g., "Type A", "Type B", "Type C"):**
- Some plans first list coverage for groups ("Type A: 100%, Type B: 80%, ...") and then, elsewhere in the document, define which services belong to each type ("Type A: Exams, Cleanings, ...").
- For each requested field, identify the matching type for that service, and use the coverage value for that type (for the appropriate network, e.g., In-Network or Out-of-Network).
- You may need to **cross-reference** information across different sections or tables.

**How to learn from the sample pairs:**
- Study ALL provided sample pairs as a set, not just the most similar one.
- Consider each mapping strategy shown: some samples may map fields directly, others require grouping logic (e.g. 'Type A/B/C' plus definitions).
- Generalize the extraction approach across all samples when processing the target PDF.
- For the target, decide on the correct mapping logic for each field—even if it involves multiple steps (e.g. cross-referencing type groupings).

**Output:** Return the JSON object only, with all above fields and no extra.
"""

    user_prompt = ""
    for i, (sample_pdf_text, sample_json) in enumerate(sample_pairs):
        user_prompt += f"SAMPLE PDF TEXT #{i+1}:\n-----\n{sample_pdf_text[:12000]}\n-----\n"
        user_prompt += f"SAMPLE PLAN JSON #{i+1}:\n{json.dumps(sample_json, indent=2)}\n-----\n"

    print(f"len is dest pdf text: {len(dest_pdf_text)}")
    user_prompt += f"TARGET PDF TEXT:\n-----\n{dest_pdf_text[:12000]}\n-----\n"
    user_prompt += "Output the target's JSON only:"

    resp = client.chat.completions.create(
        model=OPENAI_GPT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1, max_tokens=2048
    )
    result_json = resp.choices[0].message.content
    try:
        parsed = json.loads(result_json)
    except Exception:
        # Sometimes GPT adds markdown code fencing
        result_json = result_json[result_json.find("{"):result_json.rfind("}")+1]
        parsed = json.loads(result_json)

    print(f"parsed is \n: {parsed}")
    return parsed