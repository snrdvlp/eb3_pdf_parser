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

Carefully review each sample pair. Consider how each output JSON field in the sample maps to the corresponding text or table row in the sample PDF text—paying close attention to the exact table label, field name, or surrounding words. Learn the field-matching logic from these examples. When processing the target, use this logic to extract each field only from the most relevant location in the target text or tables (e.g., "Crowns" should come only from a 'Crowns' row, not similar but different terms like "Stainless Steel Crowns").

Samples below are for demonstrating extraction logic, not to provide values (do not copy values except for fallback fields: [Member Website, Out of Network Explanation, Customer Service Phone Number]).

For all numerical values (percentages, dollar limits, etc), use ONLY the target input, never a sample.

Extract ONLY these fields:
{keys_str}

For each field, if missing, set its value to "" (never null). Never omit a key. Output JSON only, with the fields above and no extras.
"""

    user_prompt = ""
    for i, (sample_pdf_text, sample_json) in enumerate(sample_pairs):
        user_prompt += f"SAMPLE PDF TEXT #{i+1}:\n-----\n{sample_pdf_text[:2000]}\n-----\n"
        user_prompt += f"SAMPLE PLAN JSON #{i+1}:\n{json.dumps(sample_json, indent=2)}\n-----\n"

    user_prompt += f"TARGET PDF TEXT:\n-----\n{dest_pdf_text[:2000]}\n-----\n"
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
    return parsed