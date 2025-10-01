import json
import re
import time
import math
import asyncio
from .category_key_registry import get_required_keys

CARRIER_DEFAULT_LIKE_KEYS = [
    "Member Website",
    "Customer Service Phone Number"
]

SPECIAL_PROMPT_INSTRUCTIONS = {
    "dental": """
**EXCEPTION FOR UNITEDHEALTHCARE PLANS:**
- If the plan is identified as "UnitedHealthcare" (by carrier name or branding in the PDF), for the fields "Single Deductible" and "Family Deductible" (both In-Network and Out-of-Network), you MAY copy these values from the matched sample JSON instead of the target PDF, to ensure correct mapping. This exception applies only to these deductible fields for UnitedHealthcare plans.
---
**CRITICAL FIELD EXTRACTION FOR SPECIFIC BENEFITS:**
- For the following fields: "Cleanings", "Exams", "X-Rays", "Sealants", "Fillings", "Simple Extractions", "Root Canal", "Periodontal Gum Disease", "Oral Surgery", "Crowns", "Dentures", "Bridges", "Implants", "Orthodontia" (both In-Network and Out-of-Network), you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
- Also, these fields represent number(percentage or price), NO other words or explanation is correct, so find the correct values.
- These fields can be displayed in DIRECT table mapping type or CLASSIFIED layouts types, so you have to consider it, review all fields one by one, so that no one field is missing it's value, especially "x-rays".
""",
    "vision": """
**CRITICAL FIELD EXTRACTION FOR VISION BENEFITS:**
- For the following fields: "Eye Exam", "Single Vision Lens", "Lined Bi-Focal Lens", "Lined Tri-Focal Lens", "Lenticular Lens", "Contact Lens Allowance", "Frame Allowance", you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
- These fields can be displayed in DIRECT table mapping type or CLASSIFIED layouts types, so you have to consider it, review all fields one by one, so that no one field is missing it's value.
""",
    "term life":"""
""",
    "std":"""
**CRITICAL FIELD EXTRACTION FOR STD BENEFITS:**
- For the following fields: "Elimination Period", "Payment Period", "Pre-Existing Conditions", you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
""",
    "ltd":"""
**CRITICAL FIELD EXTRACTION FOR LTD BENEFITS:**
- For the following fields: "Elimination Period", "Payment Period", "Pre-Existing Conditions", "Own Occupation Limitation", you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
""",
    "accident":"""
**CRITICAL FIELD EXTRACTION FOR ACCIDENT BENEFITS:**
- For the following fields: "Burn - 2nd Degree", "Burn - 3rd degree", "Coma", "Concussion", "Dental Injury", "Dislocation - Hip", "Dislocation - Knee", "Dislocation - Shoulder", "Fracture - Hip", "Fracture - Skull", "Fracture - Arm", "Fracture - Hand", you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
""",
    "critical illness":"""
**CRITICAL FIELD EXTRACTION FOR CRITICAL ILLNESS BENEFITS:**
- For the following fields: "Child Scheduled Benefit", "Guaranteed Insurability", "Pre-Existing Condition Clause", "Wellness Benefit", "Cancer", "Cancer - Carcinoma in situ", "Heart Attack", "Major Organ Failure", "Stroke", you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
""",
    "sup life":"""
**CRITICAL FIELD EXTRACTION FOR SUP LIFE BENEFITS:**
- For the following fields: "Child(ren) Life Insurance Coverage", "Accidental Death & Dismemberment", "Age Reduction Schedule", "Guaranteed Insurability", "Beneficiary", "Taxation of Benefit", you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
""",
    "health":"""
**CRITICAL FIELD EXTRACTION FOR SPECIFIC BENEFITS:**
- Interpret the following field names using these equivalences:
    * PCP Visit → may appear as: PCP, Primary Care, Primary Care Provider, Primary Care Visit
    * Specialist Visit → may appear as: Specialist, Specialist Visit
    * Urgent Care Visit → may appear as: Urgent Care, Urgent Care Visit
    * ER Visit → may appear as: ER, Emergency Medical, ER Visit, Emergency Medical Visit

- Break down coverage by drug category (Generic RX, Brand RX, Tier 3 RX, Tier 4 RX, Tier 5 RX).
    Tier 3 RX means Non-preferred brand Drugs.
    Tier 5 RX means Non-preferred Specialty Drugs. The values are displayed after "Tier 4 RX" values.
    Tier 4 RX means Preferred Specialty Drugs. The values are displayed after "Tier 3 RX" values.
    Also infer tier ranking logic: higher tier number = higher cost to the patient (Generic RX < Brand RX < Tier 3 < Tier 4 < Tier 5).
- For the following fields: "Single Deductible", "Family Deductible", "Single OOP Max", "Family OOP Max", "Coinsurance", "PCP", "Specialist", "Urgent Care Visit", "ER Visit", "Preventive Visit", "Outpatient Surgery", "Inpatient Surgery", "Newborn Delivery", "Major Diagnostics", "RX Deductible", "Generic RX", "Brand RX", "Tier 3 RX", "Tier 4 RX", "Tier 5 RX", "Mail Order RX"(both In-Network and Out-of-Network), generally the In-Network and Out-of-Network values are placed next to each other, you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
- These fields can be displayed in DIRECT table mapping type or CLASSIFIED layouts types, so you have to consider it, review all fields, so that no one field is missing it's value, especially "PCP", "Specialist", "Urgent Care Visit", "ER Visit", "Preventive Visit", "specialist", "Generic RX", "Brand RX", "Tier 3 RX", "Tier 4 RX", "Tier 5 RX" fields.
"""
    # Add more categories as needed...
}

def filter_to_required_keys(predicted: dict, required_keys: list):
    """Retain only required keys, fill blanks if missing."""
    return {k: predicted.get(k, "") for k in required_keys}


def get_system_prompt(category, required_keys):
    # keys_str = "\n".join([f'- "{k}"' for k in required_keys])
    category = category.lower()
    special_instructions = SPECIAL_PROMPT_INSTRUCTIONS.get(category, "")

    system_prompt = f"""
You are a highly accurate insurance PDF-to-JSON converter.
**Your task:** Extract specific insurance benefits and details, using ONLY the target PDF text provided, into the JSON fields listed below.
---
**CRITICAL EXTRACTION RULES:**
- For every field, extract values *only and exactly from the target PDF text*. NEVER use, infer, or copy values from sample pairs for these fields, especially about price and percent values.
- If a field is not present in the target PDF, return an empty string ("").
- Fields starting with "In-Network" or "Out-of-Network" should be a numeric value (percent or price values) or "No charge", "Not covered", "0%", but not the words like (1 per tooth, 12 months, etc)
- If multiple prices or values are listed for a benefit field, ALWAYS select the highest price or percentage value.**
- "Customer Service Phone Number" should be a phone number, not other types like email.
---
{special_instructions}
---
**Sample pairs:** Are provided ONLY to help you learn the possible ways insurance information is presented and mapped.
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
Extract and output ONLY these fields (no extras and case-insensitive):
{required_keys}
---
**Output:** Output only the completed JSON object with all fields above, and nothing else.
"""
    return system_prompt

SYSTEM_PROMPT_CACHE = {}

def get_cached_system_prompt(category):
    cat = category.lower()
    if cat in SYSTEM_PROMPT_CACHE:
        return SYSTEM_PROMPT_CACHE[cat]
    required_keys = get_required_keys(category)
    system_prompt = get_system_prompt(category, required_keys)
    SYSTEM_PROMPT_CACHE[cat] = system_prompt
    return system_prompt

def tokenize_text_for_overlap(s):
    return set(re.findall(r'\w{3,}', (s or "").lower()))

def select_top_k_samples_by_overlap(dest_excerpt, sample_pairs, k):
    if not sample_pairs:
        return []
    dest_tokens = tokenize_text_for_overlap(dest_excerpt)
    scored = []
    for (sample_pdf_text, sample_json) in sample_pairs:
        score = len(dest_tokens & tokenize_text_for_overlap(sample_pdf_text))
        scored.append((score, (sample_pdf_text, sample_json)))
    scored.sort(reverse=True, key=lambda x: x[0])
    top = [pair for score, pair in scored[:k]]
    if all(score == 0 for score, _ in scored):
        return sample_pairs[:k]
    return top

async def ask_llm_mapping_logic(
    llm,
    sample_pairs,
    dest_pdf_text: str,
    category: str,
    top_k_samples: int = 1
) -> dict:
    t0 = time.perf_counter()

    system_prompt = get_cached_system_prompt(category)

    # Select sample pairs (cheap op, keep sync)
    selected_samples = select_top_k_samples_by_overlap(dest_pdf_text, sample_pairs, k=top_k_samples)

    # Compact sample
    user_prompt_parts = []
    max_new_tokens = 512  # fallback
    for i, (s_pdf, s_json) in enumerate(selected_samples):
        compact_json = json.dumps(s_json, separators=(",", ":"))

        # Estimate tokens
        total_chars = len(compact_json)
        max_new_tokens = math.ceil(total_chars * 0.5)

        user_prompt_parts.append(
            f"SAMPLE PDF #{i+1}:\n{s_pdf[:12000]}\nSAMPLE JSON #{i+1}:\n{compact_json}\n---\n"
        )

    user_prompt_parts.append(f"TARGET PDF:\n{dest_pdf_text}\n---\n")
    user_prompt = "\n".join(user_prompt_parts)

    # # Save debug files (threadpool, so file I/O won’t block)
    # await asyncio.to_thread(lambda: open("system_prompt.txt", "w", encoding="utf-8").write(json.dumps(system_prompt)))
    # await asyncio.to_thread(lambda: open("user_prompt.txt", "w", encoding="utf-8").write(json.dumps(user_prompt)))

    print(f"max_new_token: {max_new_tokens}")

    # 🚀 Call LLM async
    raw = await llm.chat(system_prompt, user_prompt, max_new_tokens)
    # raw = asyncio.run(llm.chat(system_prompt, user_prompt, max_new_tokens))

    if isinstance(raw, dict):
        parsed = raw
    else:
        s = raw.strip() if isinstance(raw, str) else ""
        try:
            parsed = json.loads(s[s.find("{"): s.rfind("}")+1])
        except Exception as ex:
            return {"error": f"Failed to parse: {ex}", "raw": s[:400]}

    if not isinstance(parsed, dict):
        return {"error": "LLM did not return JSON."}

    parsed = replace_nulls(parsed)

    print("timing total:", round(time.perf_counter() - t0, 3), "sec")
    return parsed

def replace_nulls(obj):
    if isinstance(obj, dict):
        return {k: replace_nulls(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [replace_nulls(x) for x in obj]
    elif obj is None:
        return ""
    else:
        return obj