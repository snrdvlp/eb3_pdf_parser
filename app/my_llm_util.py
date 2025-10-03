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
    "dental": (
        "UNH deductible exception allowed for Single/Family deductibles.\n"
        "MANDATORY: For Cleanings, Exams, X-Rays, Sealants, Fillings, Extractions, Root Canal, "
        "Periodontal, Oral Surgery, Crowns, Dentures, Bridges, Implants, Orthodontia -> "
        "use ONLY target PDF values; return numeric/price/percent or empty if missing."
    ),
    "vision": (
        "MANDATORY: For Eye Exam, Single Vision Lens, Bi‑Focal, Tri‑Focal, Lenticular, "
        "Contact Lens Allowance, Frame Allowance -> use ONLY target PDF values; empty if missing."
    ),
    "std": "MANDATORY: Elimination Period, Payment Period, Pre‑Existing Conditions -> target PDF only.",
    "ltd": "MANDATORY: Elimination Period, Payment Period, Pre‑Existing Conditions, Own Occupation Limitation -> target PDF only.",
    "accident": "MANDATORY: specified accident benefit fields -> target PDF only.",
    "critical illness": "MANDATORY: specified CI fields -> target PDF only.",
    "sup life": "MANDATORY: specified supplemental life fields -> target PDF only.",
    "health": (
        "MANDATORY: Deductibles, OOP, Coinsurance, PCP/Specialist/Urgent/ER, RX tiers, Mail Order -> "
        "use ONLY target PDF values; map synonyms (PCP→Primary Care, etc.); empty if missing."
    ),
}

# compact helper to join required keys on single line
def _join_keys(required_keys):
    return ", ".join(required_keys)

def filter_to_required_keys(predicted: dict, required_keys: list):
    """Retain only required keys, fill blanks if missing."""
    return {k: predicted.get(k, "") for k in required_keys}


def get_system_prompt(category, required_keys, verbose=False):
    """
    Compact system prompt preserving all critical rules.
    Set verbose=True to return the original verbose prompt for debugging.
    """
    if verbose:
        # fallback to original long version (keep as-is if debugging)
        return get_system_prompt.__wrapped__(category, required_keys) if hasattr(get_system_prompt, "__wrapped__") else ""
    cat = (category or "").lower()
    special = SPECIAL_PROMPT_INSTRUCTIONS.get(cat, "")
    keys_line = _join_keys(required_keys)

    prompt = (
        "You are an insurance PDF→JSON extractor.\n"
        "RULES:\n"
        "- Use ONLY the TARGET PDF to extract field VALUES (unless explicit fallbacks allowed).\n"
        "- If a field is absent: return empty string \"\".\n"
        "- Numeric/price/percent fields must be numeric/price/% or 'No charge'/'Not covered'.\n"
        "- If multiple numeric options exist, return the HIGHEST applicable value.\n"
        "- Map common synonyms (e.g., PCP=Primary Care). Keep mapping only from target PDF.\n"
        f"{('- ' + special + '\\n') if special else ''}"
        "- Sample pairs are EXAMPLES of mapping logic only; DO NOT copy their values.\n"
        f"REQUIRED_KEYS: {keys_line}\n"
        "OUTPUT: Return only a JSON object with exactly the required keys (case-insensitive keys).\n"
    )
    return prompt

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
        max_new_tokens = math.ceil(total_chars * 0.6) + 50

        user_prompt_parts.append(
            f"SAMPLE PDF #{i+1}:\n{s_pdf}\nSAMPLE JSON #{i+1}:\n{compact_json}\n---\n"
        )

    user_prompt_parts.append(f"TARGET PDF:\n{dest_pdf_text}\n---\n")
    user_prompt = "\n".join(user_prompt_parts)

    # Save debug files (threadpool, so file I/O won’t block)
    await asyncio.to_thread(lambda: open("system_prompt.txt", "w", encoding="utf-8").write(json.dumps(system_prompt)))
    await asyncio.to_thread(lambda: open("user_prompt.txt", "w", encoding="utf-8").write(json.dumps(user_prompt)))

    print(f"max_new_token: {max_new_tokens}")

    # 🚀 Call LLM async
    raw = await llm.chat(system_prompt, user_prompt, max_new_tokens)

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