import re
import os
from openai import OpenAI

FIELD_ALIASES = {
    "In-Network Crowns": ["crowns", "crown"],
    "In-Network Implants": ["implants"],
    "In-Network Dentures": ["full & partial dentures", "dentures", "partial dentures", "complete dentures"],
    # Add more fields and aliases as needed!
}

def find_all_candidates(pdf_text, field_aliases):
    # Returns {"Field Name": [(line, value), ...], ...}
    out = {}
    for field, aliases in field_aliases.items():
        hits = []
        lines = pdf_text.splitlines()
        for line in lines:
            line_stripped = line.strip().lower()
            # Special case for "In-Network Crowns": require exact match to "crowns" label, not substring
            if field == "In-Network Crowns":
                for alias in aliases:
                    alias_stripped = alias.strip().lower()
                    # Match line that is exactly "crowns" or starts with "crowns " (e.g., "Crowns Not Covered")
                    if line_stripped == alias_stripped or line_stripped.startswith(alias_stripped + " "):
                        m = re.search(r'([\d,]+%|\$[\d,]+|Not Covered)', line, re.IGNORECASE)
                        if m:
                            hits.append((line.strip(), m.group(1).strip()))
            else:
                if any(alias.lower() in line_stripped for alias in aliases):
                    m = re.search(r'([\d,]+%|\$[\d,]+)', line)
                    if m:
                        hits.append((line.strip(), m.group(1).strip()))
        if hits:
            out[field] = hits
    return out

def choose_best_candidates_for_all_fields(field_candidates):
    """
    field_candidates: dict of {field: [(line, value), ...]}
    Returns: dict of {field: value}
    """
    if not field_candidates:
        return {}
    
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    prompt = (
        "You are extracting dental/insurance benefits. "
        "For each output field, you are given lines from a plan document that may contain values for that field. "
        "For each field, pick which value fits the field best (based on the line's wording, not just the number).\n"
        "Reply ONLY with a compact JSON mapping each field to its best value. Use blank string if none fit.\n\n"
    )
    for field, candidates in field_candidates.items():
        prompt += f"Field: \"{field}\"\n"
        for txt, val in candidates:
            prompt += f"- \"{txt}\" (value: {val})\n"
        prompt += "\n"
    prompt += "JSON:"
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=500
    )
    # Extract JSON
    content = resp.choices[0].message.content
    import json
    try:
        result = json.loads(content)
    except Exception:
        # If LLM wraps in markdown or similar, strip it:
        content = content[content.find("{"):content.rfind("}")+1]
        result = json.loads(content)
    return result

def refine_result_json_with_batch_llm(result_json, pdf_text, field_aliases=FIELD_ALIASES):
    candidates = find_all_candidates(pdf_text, field_aliases)
    if not candidates:
        return result_json, []
    best_vals = choose_best_candidates_for_all_fields(candidates)
    updated_fields = []
    for field, best_val in best_vals.items():
        if best_val and (not result_json.get(field) or result_json[field] != best_val):
            result_json[field] = best_val
            updated_fields.append((field, best_val))
    return result_json, updated_fields
