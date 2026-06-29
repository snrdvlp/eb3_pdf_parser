import json
import re
import time
import math
import asyncio
from .category_key_registry import get_required_keys

# Similarity threshold for using sample pairs in LLM prompt
# If distance < SIMILARITY_THRESHOLD, use samples; otherwise extract without samples
SIMILARITY_THRESHOLD = 0.17

CARRIER_DEFAULT_LIKE_KEYS = [
    "Member Website",
    "Customer Service Phone Number"
]

FIELD_EXPLANATIONS = {
    "health": {
        "Carrier Name": "Name of the insurance company providing the plan (e.g., Blue Cross Blue Shield, Aetna, UnitedHealthcare).",
        "Plan Name": "The specific name of the health insurance plan offered by the carrier. (e.g., PPO Gold 3500, PPO Silver 2500, ABCD, HIKL, LT1M, etc, not just the carrier name or other words like Select Plus).",
        "In-Network Single Deductible": "Annual deductible amount an individual must pay for covered services with in-network providers before the plan begins paying.",
        "In-Network Family Deductible": "Total deductible amount a family must pay for covered services with in-network providers before the plan begins paying.",
        "Out-of-Network Single Deductible": "Annual deductible amount an individual must pay for covered services with out-of-network providers before the plan begins paying.",
        "Out-of-Network Family Deductible": "Total deductible amount a family must pay for covered services with out-of-network providers before the plan begins paying.",
        "In-Network Single OOP Max": "Maximum out-of-pocket amount an individual pays in a plan year for in-network covered services; after this, the plan pays 100% of covered costs.",
        "In-Network Family OOP Max": "Maximum total out-of-pocket amount a family pays in a plan year for in-network covered services.",
        "Out-of-Network Single OOP Max": "Maximum out-of-pocket amount an individual pays in a plan year for covered services from out-of-network providers.",
        "Out-of-Network Family OOP Max": "Maximum total out-of-pocket amount a family pays in a plan year for covered services from out-of-network providers.",
        "In-Network Coinsurance": "Percentage of costs the member pays for covered services after meeting the in-network deductible.",
        "Out-of-Network Coinsurance": "Percentage of costs the member pays for covered services after meeting the out-of-network deductible.",
        "In-Network PCP Visit": "Member copay or coinsurance for a visit to a Primary Care Provider with in-network providers.",
        "Out-of-Network PCP Visit": "Member copay or coinsurance for a Primary Care Provider visit with out-of-network providers.",
        "In-Network Specialist Visit": "Member cost for visiting a medical specialist with in-network providers.",
        "Out-of-Network Specialist Visit": "Member cost for visiting a medical specialist with out-of-network providers.",
        "In-Network Urgent Care Visit": "Member cost for urgent care services at an in-network urgent care facility.",
        "Out-of-Network Urgent Care Visit": "Member cost for urgent care services at an out-of-network facility.",
        "In-Network ER Visit": "Member cost for emergency room services at an in-network hospital.",
        "Out-of-Network ER Visit": "Member cost for emergency room services at an out-of-network hospital.",
        "In-Network Preventive Visit": "Cost for preventive care services (annual physicals, screenings) with in-network providers; often no charge.",
        "Out-of-Network Preventive Visit": "Cost for preventive care services with out-of-network providers.",
        "In-Network Outpatient Surgery": "Member cost for outpatient surgical procedures with in-network providers.",
        "Out-of-Network Outpatient Surgery": "Member cost for outpatient surgery with out-of-network providers.",
        "In-Network Inpatient Surgery": "Member cost for surgeries requiring hospital admission with in-network providers.",
        "Out-of-Network Inpatient Surgery": "Member cost for inpatient surgery with out-of-network providers.",
        "In-Network Newborn Delivery": "Member cost for childbirth or newborn delivery services with in-network providers or hospitals.",
        "Out-of-Network Newborn Delivery": "Member cost for childbirth or newborn delivery services with out-of-network providers.",
        "In-Network Major Diagnostics": "Member cost for major diagnostic services (MRI, CT, advanced imaging) with in-network providers.",
        "Out-of-Network Major Diagnostics": "Member cost for major diagnostic services with out-of-network providers.",
        "In-Network RX Deductible": "Prescription drug deductible that must be met before in-network prescription benefits begin.",
        "Out-of-Network RX Deductible": "Prescription drug deductible that applies to prescriptions filled at out-of-network pharmacies.",
        "In-Network Generic RX": "Member cost for generic prescription drugs at in-network pharmacies (retail, not mail-order).",
        "Out-of-Network Generic RX": "Member cost for generic prescription drugs at out-of-network pharmacies (retail, not mail-order).",
        "In-Network Brand RX": "Member cost for preferred brand-name prescription drugs at in-network pharmacies (retail, not mail-order).",
        "Out-of-Network Brand RX": "Member cost for preferred brand-name prescription drugs at out-of-network pharmacies (retail, not mail-order).",
        "In-Network Tier 3 RX": "Member cost for non-preferred brand or Tier 3 prescription drugs at in-network pharmacies (retail, not mail-order).",
        "Out-of-Network Tier 3 RX": "Member cost for Tier 3 prescription drugs at out-of-network pharmacies (retail, not mail-order).",
        "In-Network Tier 4 RX": "Member cost for specialty or high-cost Tier 4 prescription drugs at in-network pharmacies (retail, not mail-order).",
        "Out-of-Network Tier 4 RX": "Member cost for Tier 4 prescription drugs at out-of-network pharmacies (retail, not mail-order).",
        "In-Network Tier 5 RX": "Member cost for highest-tier or specialty Tier 5 prescription drugs at in-network pharmacies (retail, not mail-order).",
        "Out-of-Network Tier 5 RX": "Member cost for Tier 5 prescription drugs at out-of-network pharmacies (retail, not mail-order).",
        "In-Network Mail Order RX": "Member cost for prescriptions obtained through an in-network mail-order pharmacy service (90-day supply or similar).",
        "Out-of-Network Mail Order RX": "Member cost for prescriptions obtained through a mail-order pharmacy outside the network (90-day supply or similar).",
        "Plan Year": "Time period during which plan benefits apply, usually a 12-month coverage period.",
        "Deductible Period": "Time frame in which the deductible accumulates, typically aligned with the plan year.",
        "Deductible Explanation": "Additional notes describing how the deductible works (embedded, combined, exceptions, etc.).",
        "Network Type": "Type of provider network used by the plan (e.g., PPO, HMO, EPO, POS).",
        "Network Name": "Specific name of the provider network associated with the plan.",
        "Member Website": "Official website where members can access plan information, find providers, or manage benefits.",
        "Customer Service Phone Number": "Phone number members can call for questions about health plan benefits or coverage."
    }
}

SPECIAL_PROMPT_INSTRUCTIONS = {
    "dental": """
**EXCEPTION FOR UNITEDHEALTHCARE PLANS:**
- If the plan is identified as "UnitedHealthcare" (by carrier name or branding in the PDF), for the fields "Single Deductible" and "Family Deductible" (both In-Network and Out-of-Network), you MAY copy these values from the matched sample JSON instead of the target PDF, to ensure correct mapping. This exception applies only to these deductible fields for UnitedHealthcare plans.
---
**CRITICAL FIELD EXTRACTION FOR SPECIFIC BENEFITS:**
- For the following fields: "Cleanings", "Exams", "X-Rays", "Sealants", "Fillings", "Simple Extractions", "Root Canal", "Periodontal Gum Disease", "Oral Surgery", "Crowns", "Dentures", "Bridges", "Implants", "Orthodontia" (both In-Network and Out-of-Network), you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
- Extract the EXACT value as it appears in the PDF - this includes percentages, prices, and descriptive text phrases like "Not covered", "No charge", "No Charge after deductible", etc. Extract whatever text/value the PDF shows for these fields.
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

- **Major Diagnostics / Imaging (In-Network and Out-of-Network):**
    * "In-Network Major Diagnostics" and "Out-of-Network Major Diagnostics" must be filled from the row in the SBC table whose "Services You May Need" cell refers to imaging or advanced diagnostics.
    * Treat as a Major Diagnostics / Imaging row any "Services You May Need" text that, case-insensitively, contains ANY of:
        - "imaging"
        - "ct"
        - "mri"
        - "pet"
        - "advanced imaging"
        - "major diagnostic"
        - "diagnostic imaging"
    * From that row:
        - The value in the "Network Provider (You will pay the least)" column goes to "In-Network Major Diagnostics".
        - The value in the "Out-of-Network Provider (You will pay the most)" column goes to "Out-of-Network Major Diagnostics".
    * Normalize these values when deciding what to output:
        - If the cell contains "No charge" (case-insensitive), treat it as a 0-cost value such as "No charge" or "0% coinsurance".
        - If the cell says "Not covered", set the corresponding field to an empty string ("") (do not invent a percentage).
        - Ignore any extra explanatory text like "after deductible" or "prior authorization required" when determining the numeric coinsurance; focus on the main numeric copay/coinsurance phrase.

- Break down coverage by drug category (Generic RX, Brand RX, Tier 3 RX, Tier 4 RX, Tier 5 RX).
    Tier 1 RX generally corresponds to Generic drugs.
    Tier 2 RX generally corresponds to Preferred brand drugs.
    Tier 3 RX means Non-preferred brand Drugs.
    Tier 4 RX generally corresponds to Specialty or high-cost drugs.
    Tier 5 RX means Non-preferred Specialty Drugs. The values are displayed after "Tier 4 RX" values.
    Also infer tier ranking logic: higher tier number = higher cost to the patient (Generic RX < Brand RX < Tier 3 < Tier 4 < Tier 5).
- **CRITICAL: Tier-Based RX Field Extraction Rules:**
    * Each tier-based RX field ("Generic RX", "Brand RX", "Tier 3 RX", "Tier 4 RX", "Tier 5 RX") must contain ONLY the value for that specific tier/level.
    * "Generic RX" field = extract ONLY the value for Generic/Tier 1 drugs.
    * "Brand RX" field = extract ONLY the value for Brand/Tier 2 drugs.
    * "Tier 3 RX" field = extract ONLY the value for Tier 3 drugs.
    * "Tier 4 RX" field = extract ONLY the value for Tier 4 drugs.
    * "Tier 5 RX" field = extract ONLY the value for Tier 5 drugs.
    * Do NOT include multiple tier values in a single field. Do NOT copy all tier information into each field.
    * Extract only the specific value (e.g., "$10 copay", "20%", "Not covered") for that tier, not descriptions of all tiers.
- **CRITICAL: Mail Order RX Extraction Rules:**
    * "In-Network Mail Order RX" and "Out-of-Network Mail Order RX" are NOT explicitly mentioned as independent rows in the PDF. They must be DERIVED from tier-related keys (tier1, tier2, tier3, tier4, tier5, or similar naming variations) that specifically mention "mail order", "order", "home delivery", or similar non-retail delivery methods.
    * The tier1, tier2, tier3, tier4, tier5 values (for "Generic RX", "Brand RX", "Tier 3 RX", "Tier 4 RX", "Tier 5 RX" fields) must contain ONLY retail pharmacy (non-mail-order) values. Do NOT include mail order values in these retail tier fields.
    * When extracting Mail Order RX values, look for tier columns/rows that are labeled with "mail order", "order", "home delivery", "90-day supply", or similar non-retail indicators (NOT "retail", "30-day supply", or standard pharmacy terms).
    * Format Mail Order RX values using forward slashes to separate tier values, like: "$30 / $80 / $150" (where each value corresponds to a tier: Generic/Brand/Tier3, etc., in order). If a tier doesn't have a mail order value, you may omit it or use "Not covered" as appropriate.
- For the following fields: "Single Deductible", "Family Deductible", "Single OOP Max", "Family OOP Max", "Coinsurance", "PCP", "Specialist", "Urgent Care Visit", "ER Visit", "Preventive Visit", "Outpatient Surgery", "Inpatient Surgery", "Newborn Delivery", "Major Diagnostics", "RX Deductible", "Generic RX", "Brand RX", "Tier 3 RX", "Tier 4 RX", "Tier 5 RX", "Mail Order RX"(both In-Network and Out-of-Network), generally the In-Network and Out-of-Network values are placed next to each other, you MUST extract their values ONLY from the target PDF text. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
- These fields can be displayed in DIRECT table mapping type or CLASSIFIED layouts types, so you have to consider it, review all fields, so that no one field is missing it's value, especially "PCP", "Specialist", "Urgent Care Visit", "ER Visit", "Preventive Visit", "specialist", "Generic RX", "Brand RX", "Tier 3 RX", "Tier 4 RX", "Tier 5 RX" fields.
- IMPORTANT: Some document (i.e., summary benefits) could include several plans - so in that case, don't confuse (plan1, plan2) with (in-network, out-of-network).

""",
    "health_3tier":"""
**CRITICAL: THREE-TIER NETWORK STRUCTURE - Designated Network, In-Network, and Out-of-Network:**
- This plan has THREE separate network tiers: (1) Designated Network, (2) In-Network, and (3) Out-of-Network.
- Each benefit field has THREE corresponding values that MUST be extracted separately:
    * "Designated Network [Field]" = values for Designated Network providers/services
    * "In-Network [Field]" = values for In-Network providers/services  
    * "Out-of-Network [Field]" = values for Out-of-Network providers/services
- **CRITICAL: Do NOT confuse or mix values between the three network tiers.**
- **Designated Network may be labeled as:** "Designated Network", "Designated", "DN", "Tier 1", "Preferred Network", "Primary Network", or similar labels indicating the most preferred/least expensive network tier.
- **In-Network may be labeled as:** "In-Network", "In Network", "Network", "Tier 2", "Standard Network", or similar.
- **Out-of-Network may be labeled as:** "Out-of-Network", "Out of Network", "Non-Network", "OON", "Tier 3", or similar.
- In tables, these three tiers typically appear as three separate columns. Identify which column represents which tier based on column headers, labels, or positioning (usually Designated Network = best rates, Out-of-Network = highest rates).

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
- **CRITICAL: Tier-Based RX Field Extraction Rules:**
    * Each tier-based RX field ("Generic RX", "Brand RX", "Tier 3 RX", "Tier 4 RX", "Tier 5 RX") must contain ONLY the value for that specific tier/level.
    * "Generic RX" field = extract ONLY the value for Generic/Tier 1 drugs.
    * "Brand RX" field = extract ONLY the value for Brand/Tier 2 drugs.
    * "Tier 3 RX" field = extract ONLY the value for Tier 3 drugs.
    * "Tier 4 RX" field = extract ONLY the value for Tier 4 drugs.
    * "Tier 5 RX" field = extract ONLY the value for Tier 5 drugs.
    * Do NOT include multiple tier values in a single field. Do NOT copy all tier information into each field.
    * Extract only the specific value (e.g., "$10 copay", "20%", "Not covered") for that tier, not descriptions of all tiers.
- **CRITICAL: Mail Order RX Extraction Rules:**
    * "Designated Network Mail Order RX", "In-Network Mail Order RX", and "Out-of-Network Mail Order RX" are NOT explicitly mentioned as independent rows in the PDF. They must be DERIVED from tier-related keys (tier1, tier2, tier3, tier4, tier5, or similar naming variations) that specifically mention "mail order", "order", "home delivery", or similar non-retail delivery methods.
    * The tier1, tier2, tier3, tier4, tier5 values (for "Generic RX", "Brand RX", "Tier 3 RX", "Tier 4 RX", "Tier 5 RX" fields) must contain ONLY retail pharmacy values. Do NOT include mail order values in these retail tier fields.
    * When extracting Mail Order RX values, look for tier columns/rows that are labeled with "mail order", "order", "home delivery", "90-day supply", or similar non-retail indicators (NOT "retail", "30-day supply", or standard pharmacy terms).
    * Format Mail Order RX values using forward slashes to separate tier values, like: "$30 / $80 / $150" (where each value corresponds to a tier: Generic/Brand/Tier3, etc., in order). If a tier doesn't have a mail order value, you may omit it or use "Not covered" as appropriate.
- For ALL fields with "Designated Network", "In-Network", and "Out-of-Network" variants: "Single Deductible", "Family Deductible", "Single OOP Max", "Family OOP Max", "Coinsurance", "PCP", "Specialist", "Urgent Care Visit", "ER Visit", "Preventive Visit", "Outpatient Surgery", "Inpatient Surgery", "Newborn Delivery", "Major Diagnostics", "RX Deductible", "Generic RX", "Brand RX", "Tier 3 RX", "Tier 4 RX", "Tier 5 RX", "Mail Order RX", you MUST extract their values ONLY from the target PDF text for EACH of the THREE network tiers separately. Do NOT infer, guess, or copy these values from any sample JSONs, regardless of similarity.
- **CRITICAL: Network Tier Separation Rules:**
    * Extract Designated Network values ONLY from columns/sections explicitly labeled as "Designated Network" or equivalent terms.
    * Extract In-Network values ONLY from columns/sections explicitly labeled as "In-Network" or equivalent terms.
    * Extract Out-of-Network values ONLY from columns/sections explicitly labeled as "Out-of-Network" or equivalent terms.
    * **NEVER copy values from one network tier to another.** If a network tier is not present in the PDF, leave its fields as empty string ("").
    * If the PDF shows only Designated Network and In-Network (but not Out-of-Network), extract those two only and leave Out-of-Network fields empty.
    * If the PDF shows only In-Network and Out-of-Network (but not Designated Network), extract those two only and leave Designated Network fields empty.
    * Do NOT assume all three tiers have values - only extract values that are explicitly shown for each tier in the PDF.
- These fields can be displayed in DIRECT table mapping type or CLASSIFIED layouts types, so you have to consider it, review all fields, so that no one field is missing it's value, especially "PCP", "Specialist", "Urgent Care Visit", "ER Visit", "Preventive Visit", "specialist", "Generic RX", "Brand RX", "Tier 3 RX", "Tier 4 RX", "Tier 5 RX" fields for EACH of the three network tiers.
- IMPORTANT: Some document (i.e., summary benefits) could include several plans - so in that case, don't confuse (plan1, plan2) with (Designated Network, In-Network, Out-of-Network).

"""
    # Add more categories as needed...
}

def _join_keys(required_keys):
    """Compact helper to join required keys on a single line."""
    return ", ".join(required_keys)

def build_field_hints_block(category: str, required_keys: list, max_tokens: int = 1500) -> str:
    """
    Build a compact block of field explanations for the current category.
    Uses FIELD_EXPLANATIONS but keeps the text short and enforces a token budget.
    """
    cat = (category or "").lower()
    explanations = FIELD_EXPLANATIONS.get(cat, {})
    if not explanations:
        return ""

    lines = []
    for key in required_keys:
        exp = explanations.get(key)
        if not exp:
            continue
        line = f"- **{key}**: {exp}"
        tentative = ("\n".join(lines) + ("\n" if lines else "") + line) if lines else line
        if estimate_tokens(tentative) > max_tokens:
            break
        lines.append(line)

    if not lines:
        return ""

    block = "\n".join(lines)
    return "\n**Field semantics and meanings (for this category):**\n" + block + "\n"

def filter_to_required_keys(predicted: dict, required_keys: list):
    """Retain only required keys, fill blanks if missing."""
    return {k: predicted.get(k, "") for k in required_keys}


def get_system_prompt(category, required_keys, use_samples=True, verbose=False):
    """
    Compact system prompt preserving all critical rules.
    Set verbose=True to return the original verbose prompt for debugging.
    Set use_samples=False to generate prompt without sample pair instructions.
    """
    if verbose:
        # fallback to original long version (keep as-is if debugging)
        return get_system_prompt.__wrapped__(category, required_keys) if hasattr(get_system_prompt, "__wrapped__") else ""
    cat = (category or "").lower()
    special = SPECIAL_PROMPT_INSTRUCTIONS.get(cat, "")
    keys_line = _join_keys(required_keys)

    # Base extraction strategy - enhanced for without samples mode
    if use_samples:
        extraction_strategy = """**CRITICAL EXTRACTION STRATEGY:**
- **PRIMARY APPROACH:** Extract ALL required fields directly from the target PDF text based on insurance context and field names. Analyze the target PDF independently and extract values based on your understanding of insurance terminology and document structure.
- **For every field:** Extract values *only and exactly from the target PDF text*. Use your knowledge of insurance terminology and document structures to locate and extract the correct values."""
    else:
        extraction_strategy = """**CRITICAL EXTRACTION STRATEGY - TARGET PDF ONLY MODE:**
- **MANDATORY: Extract ALL Required Fields** - You MUST extract a value for EVERY field listed below. Do NOT skip any fields.
- **Systematic Field-by-Field Extraction:**
  * Go through EACH field in the required fields list one by one
  * For each field, search the entire PDF text for related information
  * Use field name variations, synonyms, and your insurance knowledge to locate values
  * If a field is present in the PDF (even if named differently), extract it
  * Only return empty string ("") if the field is completely absent from the PDF
- **Field Name Matching:**
  * Field names may appear with variations (e.g., "PCP Visit" might be "Primary Care", "PCP", "Primary Care Provider Visit")
  * Look for semantic equivalents, not just exact matches
  * Use your understanding of insurance terminology to identify field values
- **Completeness is Critical:** Missing fields indicate incomplete extraction. Be thorough and systematic."""

    # Sample pair instructions - only included if use_samples=True
    sample_instructions = ""
    if use_samples:
        sample_instructions = """
- **SECONDARY APPROACH - Use Sample Pairs Only When Needed:**
  - Use sample PDF-JSON pairs ONLY when:
    * A field's meaning or location in the target PDF is unclear or ambiguous
    * You need to understand how a particular layout/structure maps to fields (e.g., grouped layouts, tier systems)
    * The target PDF uses an unfamiliar presentation format that you cannot interpret directly
  - When using samples, use them ONLY to understand:
    * How information might be structured or organized
    * How different layouts map to fields
    * What terminology variations might exist
  - **NEVER** copy values from sample pairs - they are for reference only, not content sources.
- If a field is clearly present in the target PDF, extract it directly without referencing samples."""

    system_prompt = f"""
You are a highly accurate insurance PDF-to-JSON converter.
**Your task:** Extract specific insurance benefits and details from the target PDF text into the JSON fields listed below.
---
{extraction_strategy}{sample_instructions}
- **CRITICAL: Extract Exact Text/Value as it Appears in PDF:**
  * Extract the EXACT text or value as it appears in the PDF for each field. This includes:
    - Numeric values: percentages (e.g., "80%", "20%"), prices (e.g., "$50", "$100 copay")
    - Text phrases: "Not covered", "Not Covered", "No charge", "No Charge after deductible", "No Charge", etc.
    - Any other descriptive text that describes the coverage/benefit value in the PDF
  * DO NOT restrict yourself to only numeric values or a predefined list of phrases. Extract whatever text/value the PDF shows for that field.
  * Return an empty string ("") ONLY when the field/benefit is completely absent from the PDF text and has no mention whatsoever.
  * IMPORTANT: Any text/value found in the PDF related to a field is VALID - extract it as-is. Do NOT return empty string when you find any value or descriptive text for a field in the PDF.
- If multiple prices or values are listed for a benefit field:
  * When a line clearly shows **separate values for different roles** (e.g., individual/single vs family, or in-network vs out-of-network), map each value to its correct field (individual/single → single fields, family → family fields, in-network/participating → in-network fields, out-of-network/non-participating → out-of-network fields) instead of picking only one value.
  * In other cases where multiple numeric options exist for the **same** benefit/role (e.g., multiple copays for the same visit type), select the highest price or percentage value.
  * For descriptive text, extract the most appropriate or primary description.
- **CRITICAL: Field Value Extraction - One Value Per Field:**
    * Each field must contain ONLY the value for that specific field, not multiple values or descriptions of other fields.
    * For tier-based fields (e.g., "Generic RX", "Brand RX", "Tier 3 RX"), extract ONLY the value for that specific tier, not all tier information.
    * Do NOT include descriptions, explanations, or values from other related fields in a single field.
    * Keep field values concise and specific to that field only.
- "Customer Service Phone Number" should be a phone number, not other types like email.
---
{special}
---"""

    # Sample pair sections - only included if use_samples=True
    sample_sections = ""
    if use_samples:
        sample_sections = """
**Sample pairs:** Are provided ONLY as reference when you encounter unclear or ambiguous field mappings. Do NOT rely on them if the target PDF is clear and self-explanatory.
---
**Sample Pair Usage Rules:**
- **When to use samples:** Only consult sample pairs when the target PDF structure is unclear or you cannot determine how to map a field. If the target PDF is clear and self-explanatory, extract directly without referencing samples.
- **How to use samples:** When you do need samples:
  * Review sample pairs to understand possible presentation formats (direct mapping, grouped layouts, tier systems, etc.)
  * Use them as logic references for extraction methods, NOT as content sources
  * Generalize mapping patterns from samples, but ALWAYS apply those patterns to the target PDF's actual content
  * Never copy values from samples - always extract from target PDF text
- **Priority:** Target PDF text > Your insurance knowledge > Sample pairs (only when needed)
---"""

    # Field-matching instructions - same for both versions
    field_matching = """
**Field-matching and mapping instructions:**
- **CRITICAL: Document Structure - Tables vs Text Content:**
  - The extracted PDF text contains information in TWO formats: (1) Structured markdown tables (marked with "### Table (Page X)"), and (2) Plain text blocks containing the raw content from the PDF.
  - **IMPORTANT:** The markdown tables are EXTRACTION ATTEMPTS and may contain ERRORS, be INCOMPLETE, or have MISALIGNED data. They are NOT reliable for extracting actual values.
  - **The plain text blocks contain the RAW, ORIGINAL content from the PDF** - this is the AUTHORITATIVE SOURCE and should be trusted for actual values.
  - **How to use both sources:**
    * Use the structured markdown tables ONLY as a GUIDE to understand the layout, structure, and organization of information (e.g., which columns represent In-Network vs Out-of-Network, which rows contain which benefits).
    * Extract actual values from the plain text content, NOT from the markdown tables.
    * Cross-reference both: Use the table structure to locate where information should be, then find the exact values in the corresponding text blocks.
  - **When there are discrepancies:** If you see different values in the table vs text, ALWAYS trust the text content. The text is the raw PDF content and is accurate.
  - **Example workflow:** (1) Look at table structure to understand layout, (2) Find the corresponding section in text blocks, (3) Extract exact values from text, (4) Verify against table structure if needed, but always use text values.
- **Direct table mapping:** If PDF has a simple table or list mapping benefit fields (e.g., "Crowns In-Network"), extract those values directly from the text content, using table structure only as a guide for understanding the layout.
- **Grouped or classified layouts (e.g., "Type A/B/C", "Class I/II/III", "Type 1/2/3", "Preventive/Basic/Major", etc.):**
    - You must determine each benefit's group/class only from the target PDF text itself (headings, tables, legends, or explicit mapping in that document).
    - Never use or borrow group/class assignments from any sample pair. If the target PDF does not explicitly show which group/class a benefit belongs to, set its value to "".
    - Once the benefit's group/class is identified in the target PDF, use that same PDF's coverage values for the group/class (e.g., "Type B is 90%") and assign them.
    - If the target PDF uses different labels (e.g., "Preventive/Basic/Major" instead of "Type A/B/C"), follow those exactly from the PDF. Do not assume mappings from the samples.
- **Synonyms and variations:** Recognize that "In-Network"/"Out-of-Network" may be labeled as "Tier 1/2", "PPO/Premier", "Network/Non-Network", "Preferred/Non-Preferred", etc. Map accordingly, using current PDF context.
  - For medical plans, "Participating" or "Participating Provider" generally corresponds to in-network, while "Non-Participating" or "Non-Participating Provider" generally corresponds to out-of-network. Map these correctly to the corresponding in-network or out-of-network fields.
- When a field is neither directly mapped in a table nor present in any grouping, set its value to "".
---"""

    # Output requirements - enhanced for without samples mode
    if use_samples:
        output_requirements = """
**For all fields:**  
Extract and output ONLY these fields (no extras and case-insensitive):
{keys_line}
---
**Output Requirements:**
- Output ONLY the JSON object with all fields above.
- Do NOT include any explanations, comments, or additional text.
- Do NOT include markdown code block markers (```json or ```).
- Output the raw JSON object only, starting with {{ and ending with }}.
- No explanations, no notes, no additional context - just the JSON.
"""
    else:
        num_fields = len(required_keys)
        output_requirements = f"""
**REQUIRED FIELDS - EXTRACT ALL OF THESE ({num_fields} fields):**
You MUST provide a value for EVERY field listed below. Missing fields are NOT acceptable.
{keys_line}
---
**Output Requirements:**
- **MANDATORY:** Output a JSON object with ALL {num_fields} fields listed above.
- **Every field must be present** in your output JSON, even if the value is an empty string ("").
- **Field completeness check:** Before outputting, verify you have extracted all {num_fields} fields.
- Output ONLY the JSON object with all fields above.
- Do NOT include any explanations, comments, or additional text.
- Do NOT include markdown code block markers (```json or ```).
- Output the raw JSON object only, starting with {{ and ending with }}.
- No explanations, no notes, no additional context - just the JSON.
"""

    # Optional field explanations (category-specific), token-limited
    field_hints = build_field_hints_block(category, required_keys)

    # Combine all parts
    full_prompt = system_prompt + sample_sections + field_matching + field_hints + output_requirements
    return full_prompt

SYSTEM_PROMPT_CACHE = {}

def get_cached_system_prompt(category, use_samples=True):
    """
    Get cached system prompt for category.
    use_samples: If True, includes sample pair instructions; if False, extracts without samples.
    """
    cat = category.lower()
    cache_key = f"{cat}_{use_samples}"
    if cache_key in SYSTEM_PROMPT_CACHE:
        return SYSTEM_PROMPT_CACHE[cache_key]
    required_keys = get_required_keys(category)
    system_prompt = get_system_prompt(category, required_keys, use_samples=use_samples)
    SYSTEM_PROMPT_CACHE[cache_key] = system_prompt
    return system_prompt

def tokenize_text_for_overlap(s):
    return set(re.findall(r'\w{3,}', (s or "").lower()))

def estimate_tokens(text: str) -> int:
    """
    Estimate token count from text.
    Rough approximation: ~4 characters per token for English text.
    This is a heuristic used by many LLM APIs.
    """
    if not text:
        return 0
    # Average: 1 token ≈ 4 characters for English text
    # Add some padding for special characters and whitespace
    return math.ceil(len(text) / 4)

def truncate_text_to_token_limit(text: str, max_tokens: int, suffix: str = "...") -> str:
    """
    Truncate text to fit within token limit, keeping the beginning.
    Returns truncated text that should be approximately within max_tokens.
    """
    if not text:
        return text
    estimated = estimate_tokens(text)
    if estimated <= max_tokens:
        return text
    # Calculate target character length (leave room for suffix)
    suffix_tokens = estimate_tokens(suffix)
    target_tokens = max_tokens - suffix_tokens
    target_chars = target_tokens * 4  # rough: 4 chars per token
    # Truncate and add suffix
    truncated = text[:target_chars]
    # Try to cut at a word boundary if possible
    last_space = truncated.rfind('\n')
    if last_space > target_chars * 0.9:  # Only if we're close to target
        truncated = truncated[:last_space]
    return truncated + suffix

def truncate_text_from_end(text: str, max_tokens: int) -> str:
    """
    Truncate text from the END to fit within token limit, keeping the beginning.
    Useful for sample documents where the end is less important.
    """
    if not text:
        return text
    estimated = estimate_tokens(text)
    if estimated <= max_tokens:
        return text
    # Calculate target character length (4 chars per token roughly)
    target_tokens = max_tokens
    target_chars = target_tokens * 4
    # Truncate from end - keep the beginning
    if len(text) <= target_chars:
        return text
    # Try to cut at a paragraph/section boundary (double newline)
    truncated = text[:target_chars]
    # Look for a good cut point near the target (paragraph break)
    good_cutoff = truncated.rfind('\n\n')
    if good_cutoff > target_chars * 0.85:  # If we found a break close to target
        return text[:good_cutoff]
    # Fall back to simple truncation
    return truncated

def detect_plan_level_coinsurance(pdf_text: str) -> dict:
    """
    Detect plan-level in-network and out-of-network coinsurance percentages
    from SBC-style text by scanning for '<number>% coinsurance' patterns.
    Returns a dict like:
        {"in_network_coinsurance": 20, "out_of_network_coinsurance": 50}
    or {} if nothing can be reliably inferred.
    """
    if not pdf_text:
        return {}

    pattern = re.compile(r'(\d{1,3})\s*%\s*coinsurance', re.IGNORECASE)
    matches = pattern.findall(pdf_text)
    if not matches:
        return {}

    # Convert to integers and count frequencies
    values = [int(m) for m in matches]
    if not values:
        return {}

    from collections import Counter
    counts = Counter(values)

    # Get distinct values ordered by frequency (desc) then by value (asc)
    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    if not ordered:
        return {}

    # If only one percentage appears, treat it as in-network; we can't infer OON reliably
    if len(ordered) == 1:
        in_val = ordered[0][0]
        return {"in_network_coinsurance": in_val}

    # Take the two most common distinct percentages
    top_vals = [ordered[0][0]]
    for val, _cnt in ordered[1:]:
        if val not in top_vals:
            top_vals.append(val)
        if len(top_vals) >= 2:
            break

    if len(top_vals) == 1:
        # Fallback to single value case
        return {"in_network_coinsurance": top_vals[0]}

    # Assign smaller to in-network (usually lower member cost), larger to out-of-network
    in_val, out_val = sorted(top_vals)
    return {
        "in_network_coinsurance": in_val,
        "out_of_network_coinsurance": out_val,
    }

def _split_retail_mail_rx_segments(raw: str):
    """
    Split an RX value into a primary retail segment and a list of mail-order segments.
    Returns (retail_segment: str or None, mail_segments: list[str]).
    """
    if not raw:
        return None, []
    text = str(raw)

    # Split primarily on commas; keep " / " inside segments so "$30 / prescription"
    # stays together.
    import re as _re
    segments = [_s.strip() for _s in _re.split(r",", text) if _s and _s.strip()]
    if not segments:
        return None, []

    def is_mail(seg: str) -> bool:
        ls = seg.lower()
        return ("mail" in ls) or ("home delivery" in ls) or ("90-day" in ls)

    mail_segments = [s for s in segments if is_mail(s)]

    # Candidate retail segments: non-mail segments
    retail_candidates = [s for s in segments if not is_mail(s)]
    if not retail_candidates:
        return None, mail_segments

    # Prefer candidates that contain a number (actual copay/coinsurance)
    numeric_candidates = [s for s in retail_candidates if _re.search(r"\d", s)]
    if numeric_candidates:
        return numeric_candidates[0], mail_segments

    # Fallback to the first non-mail segment
    return retail_candidates[0], mail_segments

def _normalize_retail_rx_value(raw: str) -> str:
    """
    Normalize RX tier fields to keep ONLY the retail (non-mail-order) portion
    and remove explicit "retail" markers from the value text.
    Examples:
      "20 copay/prescription (retail), 60 copay/prescription (mail)"
        -> "20 copay/prescription"
      "Not covered (mail), 20% coinsurance (retail)"
        -> "20% coinsurance"
    If no clear retail segment is found, returns the original string.
    """
    if not raw:
        return raw
    text = str(raw)

    retail_seg, _mail_segments = _split_retail_mail_rx_segments(text)
    if not retail_seg:
        return text.strip()

    import re as _re
    cleaned = retail_seg
    # Remove "(retail)" or similar markers
    cleaned = _re.sub(r"\s*\(retail\)", "", cleaned, flags=_re.IGNORECASE)
    cleaned = _re.sub(r"\s*retail\b", "", cleaned, flags=_re.IGNORECASE)
    return cleaned.strip()

def _normalize_major_diagnostics_value(raw: str):
    """
    Deprecated helper for Major Diagnostics normalization.
    Kept as a no-op placeholder to avoid breaking imports; logic now handled by LLM prompt.
    """
    return raw

async def refine_blank_fields(
    llm,
    dest_pdf_text: str,
    category: str,
    initial_json: dict,
    blank_fields: list,
    batch_size: int = 20,
) -> dict:
    """
    Second-pass refinement: for any fields that are still blank after the main extraction,
    run additional focused LLM calls to try to fill them using ONLY the target PDF text.
    Prioritizes accuracy over speed.
    """
    if not blank_fields or not dest_pdf_text:
        return initial_json

    # Short, refinement-focused system prompt, optimized for numeric/amount values.
    # We do NOT include sample pairs here to avoid contamination from sample JSON values.
    system_prompt = """
You refine an existing insurance PDF-to-JSON extraction.
Focus ONLY on extracting numeric / amount-like values (percentages, dollar amounts, copays, coinsurance, limits).

You will receive:
- Full text of a target insurance PDF.
- A JSON object with some fields (values may be empty strings "").

For EACH field:
- Search the PDF for that field and extract the MAIN numeric/amount value (e.g. "80%", "$50", "$1,000", "$30 copay").
- If the plan clearly says there is no coverage, you may use short phrases like "Not covered" or "No charge".
- Do NOT return long explanations or sentences, only the core value/phrase.
- Leave a field as empty string ("") ONLY if the PDF truly has no information for it.

Output:
- Return ONLY a JSON object with the SAME keys.
- No extra keys, no explanations, no markdown.
""".strip()

    # Token budget for refinement calls – we still keep within safety limits
    MAX_REFINEMENT_INPUT_TOKENS = 12000
    MAX_REFINEMENT_NEW_TOKENS = 2000

    pdf_tokens = estimate_tokens(dest_pdf_text)
    # Truncate PDF if needed to keep under limit while reserving space for JSON + instructions
    if pdf_tokens > MAX_REFINEMENT_INPUT_TOKENS:
        dest_pdf_text = truncate_text_to_token_limit(dest_pdf_text, MAX_REFINEMENT_INPUT_TOKENS)

    # Process blanks in batches to avoid extremely large prompts
    for i in range(0, len(blank_fields), batch_size):
        batch = blank_fields[i : i + batch_size]
        # Build a mini JSON with only the fields in this batch
        batch_json = {k: initial_json.get(k, "") for k in batch}
        batch_json_str = json.dumps(batch_json, ensure_ascii=False)

        user_prompt = f"""
TARGET PDF TEXT:
{dest_pdf_text}
---
CURRENT PARTIAL JSON (fields to refine):
{batch_json_str}
---
Update the JSON above by filling in any fields you can confidently extract from the PDF text.
Return ONLY the updated JSON object with the SAME keys.
""".strip()

        raw = await llm.chat(system_prompt, user_prompt, MAX_REFINEMENT_NEW_TOKENS)

        if isinstance(raw, dict):
            refined = raw
        else:
            s = raw.strip() if isinstance(raw, str) else ""
            try:
                refined = json.loads(s[s.find("{"): s.rfind("}")+1])
            except Exception as ex:
                # If refinement fails to parse, skip this batch but keep previous values
                print(f"Refinement parsing failed for batch {i//batch_size + 1}: {ex}")
                continue

        if not isinstance(refined, dict):
            continue

        # Merge: only overwrite fields that are currently blank and became non-empty
        for field in batch:
            current_val = initial_json.get(field, "")
            new_val = refined.get(field, current_val)
            if not isinstance(new_val, str):
                new_val = str(new_val) if new_val is not None else ""
            if (not str(current_val).strip()) and str(new_val).strip():
                initial_json[field] = new_val

    return initial_json

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
    top_k_samples: int = 1,
    use_samples: bool = True,
    refine_blanks: bool = True,
) -> dict:
    t0 = time.perf_counter()

    system_prompt = get_cached_system_prompt(category, use_samples=use_samples)
    
    # Get required keys to calculate max_new_tokens
    required_keys = get_required_keys(category)
    num_fields = len(required_keys)

    # Select sample pairs only if use_samples is True
    selected_samples = []
    if use_samples and sample_pairs:
        selected_samples = select_top_k_samples_by_overlap(dest_pdf_text, sample_pairs, k=top_k_samples)
    elif use_samples and not sample_pairs:
        print("Warning: use_samples=True but no sample_pairs provided")

    # Model limits: 32768 total context, reserve ~3000 for output, so ~29700 for input (conservative)
    # Token estimation ratio: Code estimates ~30000, but LLM sees ~34000 (ratio ~1.133)
    # Our estimation UNDERESTIMATES by factor of 1.133, so we need to be more conservative
    # If we want actual LLM tokens <= 32768, our estimated tokens should be <= 32768/1.133 = ~28900
    TOKEN_ESTIMATION_RATIO = 34000.0 / 30000.0  # ~1.133: LLM actual tokens / code estimated tokens
    MAX_INPUT_TOKENS_ACTUAL_LLM = 29700  # Target actual LLM tokens (reserve 3000 for output)
    # Our estimated tokens target: actual_target / ratio = 29700 / 1.133 = ~26200
    MAX_INPUT_TOKENS = int(MAX_INPUT_TOKENS_ACTUAL_LLM / TOKEN_ESTIMATION_RATIO)  # ~26200 estimated tokens
    
    # Estimate system prompt tokens
    system_tokens = estimate_tokens(system_prompt)
    available_tokens = MAX_INPUT_TOKENS - system_tokens - 500  # Reserve 500 for formatting/overhead
    
    # Target PDF is PRIMARY source (per system prompt: "Priority: Target PDF text > Sample pairs")
    # If we're close to limits, remove ALL samples rather than truncating target PDF
    target_section_header = "TARGET PDF:\n"
    target_header_tokens = estimate_tokens(target_section_header + "\n---\n")
    target_pdf_tokens = estimate_tokens(dest_pdf_text)
    min_tokens_for_target = target_header_tokens + target_pdf_tokens
    
    # Build user prompt
    user_prompt_parts = []
    
    # Calculate max_new_tokens based on number of required fields
    # Each field needs ~40-60 tokens (field name + value + JSON formatting)
    if use_samples:
        # With samples: estimate based on sample JSON size (existing logic)
        max_new_tokens = 512  # fallback, will be updated if samples are used
    else:
        # Without samples: need enough tokens for ALL fields
        # Estimate: ~50 tokens per field (field name + value + JSON structure)
        # Add buffer for JSON structure overhead
        estimated_tokens_needed = num_fields * 50 + 300  # 300 for JSON structure overhead
        # Use 2/3 of estimated tokens (more efficient)
        estimated_tokens_needed = int(estimated_tokens_needed * 2 / 3)
        # Ensure minimum 2000 tokens, cap at 4000 for safety
        max_new_tokens = max(2000, min(estimated_tokens_needed, 4000))
        print(f"Target PDF only mode: Setting max_new_tokens={max_new_tokens} for {num_fields} required fields")
    
    used_tokens = 0
    
    # If not using samples, simpler token management - just ensure target PDF fits
    if not use_samples:
        if min_tokens_for_target > available_tokens:
            # Target PDF alone is too large - truncate it
            max_target_tokens = available_tokens - target_header_tokens
            print(f"Warning: Target PDF alone exceeds limit. Truncating from {target_pdf_tokens} to {max_target_tokens} tokens")
            dest_pdf_text = truncate_text_to_token_limit(dest_pdf_text, max_target_tokens)
        # Add target PDF only
        user_prompt_parts.append(f"{target_section_header}{dest_pdf_text}\n---\n")
    else:
        # Strategy: Reserve space for target PDF first, then add samples only if there's room
        # If target PDF alone would exceed limit, truncate target (but this is rare)
        tokens_for_samples = 0
        if min_tokens_for_target > available_tokens:
            # Target PDF alone is too large - truncate it (last resort)
            max_target_tokens = available_tokens - target_header_tokens
            print(f"Warning: Target PDF alone exceeds limit. Truncating from {target_pdf_tokens} to {max_target_tokens} tokens")
            dest_pdf_text = truncate_text_to_token_limit(dest_pdf_text, max_target_tokens)
            selected_samples = []  # Remove all samples if target alone is too large
            tokens_for_samples = 0
        else:
            # Reserve space for target PDF, use remaining for samples
            tokens_for_samples = available_tokens - min_tokens_for_target
        
        # Add samples only if we have space (samples are optional per system prompt)
        if selected_samples and tokens_for_samples > 1000:  # Need at least 1000 tokens to be worth including samples
            for i, (s_pdf, s_json) in enumerate(selected_samples):
                oritinal_compact_json = json.dumps(s_json, separators=(",", ":"))
                # Filter out empty values so that missing fields in the sample
                # (e.g., blank out-of-network fields) do not bias extraction for
                # the target PDF. Keep only keys with non-empty values.
                filtered_json = {
                    k: v for k, v in s_json.items()
                    if v is not None and str(v).strip() != ""
                }
                compact_json = json.dumps(filtered_json, separators=(",", ":"))

                # Estimate tokens
                total_chars = len(oritinal_compact_json)
                max_new_tokens = max(max_new_tokens, math.ceil(total_chars * 0.7) + 50)

                # Calculate remaining space for samples
                remaining_for_samples = tokens_for_samples - used_tokens

                # Build sample section
                sample_header_template = f"SAMPLE PDF #{i+1}:\n\nSAMPLE JSON #{i+1}:\n{compact_json}\n---\n"
                sample_header_tokens = estimate_tokens(sample_header_template)

                # Reserve at least 500 tokens for remaining samples and target padding
                available_for_this_sample = remaining_for_samples - 500 - sample_header_tokens

                if available_for_this_sample < 100:  # Not enough space, skip remaining samples
                    print(f"Skipping sample #{i+1} and remaining samples due to token limit (target PDF takes priority)")
                    break

                # Truncate sample PDF from the END if needed (end is less important for samples)
                estimated_sample_tokens = estimate_tokens(s_pdf)
                if estimated_sample_tokens > available_for_this_sample:
                    # Apply safety margin: reduce by 10% more to account for estimation variance
                    safe_target_tokens = int(available_for_this_sample * 0.9)
                    print(f"Truncating sample #{i+1} PDF from end: {estimated_sample_tokens} to ~{safe_target_tokens} tokens")
                    s_pdf = truncate_text_from_end(s_pdf, safe_target_tokens)

                sample_section = f"SAMPLE PDF #{i+1}:\n{s_pdf}\nSAMPLE JSON #{i+1}:\n{compact_json}\n---\n"
                sample_tokens = estimate_tokens(sample_section)

                # Final check: if this would leave too little for target, skip it and remaining samples
                if used_tokens + sample_tokens > tokens_for_samples - 500:
                    print(f"Removing sample #{i+1} and remaining samples to ensure target PDF fits (target PDF takes priority)")
                    break

                user_prompt_parts.append(sample_section)
                used_tokens += sample_tokens
        elif selected_samples:
            print(f"Skipping all samples due to token limit (target PDF needs {min_tokens_for_target} tokens, only {available_tokens} available)")
        
        # Add target PDF (should already fit, but double-check)
        remaining_tokens = available_tokens - used_tokens - target_header_tokens
        if estimate_tokens(dest_pdf_text) > remaining_tokens:
            print(f"Final check: Truncating target PDF from {estimate_tokens(dest_pdf_text)} to {remaining_tokens} tokens")
            dest_pdf_text = truncate_text_to_token_limit(dest_pdf_text, remaining_tokens)
        
        user_prompt_parts.append(f"{target_section_header}{dest_pdf_text}\n---\n")
    user_prompt = "\n".join(user_prompt_parts)
    
    # Calculate total input tokens for logging
    total_input_tokens = system_tokens + estimate_tokens(user_prompt)
    print(f"Token usage: system={system_tokens}, user_prompt={estimate_tokens(user_prompt)}, total_input={total_input_tokens}, max_new_token: {max_new_tokens}")

    # # Save debug files (threadpool, so file I/O won't block)
    # await asyncio.to_thread(lambda: open("system_prompt.txt", "w", encoding="utf-8").write(json.dumps(system_prompt)))
    # await asyncio.to_thread(lambda: open("user_prompt.txt", "w", encoding="utf-8").write(json.dumps(user_prompt)))

    # raw = await llm.wrapper_request(system_prompt, user_prompt, max_new_tokens)
    raw = await llm.chat(system_prompt, user_prompt, max_new_tokens)

    print(f"---\nraw: \n{raw}\n---\n")

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
    
    # Ensure all required fields are present (fill missing with empty strings)
    required_keys = get_required_keys(category)
    parsed = filter_to_required_keys(parsed, required_keys)

    # For health plans, ensure RX tier fields contain ONLY retail (non-mail-order) values
    # and build Mail Order RX fields from the removed mail-order segments.
    cat = (category or "").lower()
    if cat in ["health", "health_3tier"]:
        rx_keys = [
            "In-Network Generic RX", "Out-of-Network Generic RX",
            "In-Network Brand RX", "Out-of-Network Brand RX",
            "In-Network Tier 3 RX", "Out-of-Network Tier 3 RX",
            "In-Network Tier 4 RX", "Out-of-Network Tier 4 RX",
            "In-Network Tier 5 RX", "Out-of-Network Tier 5 RX",
        ]

        # Map each RX key to (network, tier_index) so we can build Mail Order RX later.
        rx_meta = {
            "In-Network Generic RX": ("in", 1),
            "Out-of-Network Generic RX": ("out", 1),
            "In-Network Brand RX": ("in", 2),
            "Out-of-Network Brand RX": ("out", 2),
            "In-Network Tier 3 RX": ("in", 3),
            "Out-of-Network Tier 3 RX": ("out", 3),
            "In-Network Tier 4 RX": ("in", 4),
            "Out-of-Network Tier 4 RX": ("out", 4),
            "In-Network Tier 5 RX": ("in", 5),
            "Out-of-Network Tier 5 RX": ("out", 5),
        }

        in_mail_by_tier = {i: None for i in range(1, 6)}
        out_mail_by_tier = {i: None for i in range(1, 6)}

        import re as _re

        def _clean_mail_segment(seg: str) -> str:
            if not seg:
                return ""
            s = str(seg)
            # Remove explicit "(mail...)" markers and the word "mail" / "mail order"
            s = _re.sub(r"\s*\(mail[^\)]*\)", "", s, flags=_re.IGNORECASE)
            s = _re.sub(r"\bmail(?: order)?\b", "", s, flags=_re.IGNORECASE)
            s = _re.sub(r"\s*home delivery\b", "", s, flags=_re.IGNORECASE)
            s = _re.sub(r"\s*90-day\s*supply\b", "", s, flags=_re.IGNORECASE)
            return s.strip(" ,;/")

        for k in rx_keys:
            if k in parsed and isinstance(parsed[k], str):
                raw_val = parsed[k]
                retail_seg, mail_segments = _split_retail_mail_rx_segments(raw_val)
                # Normalize and store retail value (without "(retail)" tags)
                parsed[k] = _normalize_retail_rx_value(raw_val)

                if mail_segments:
                    # Take the first mail-order segment for this tier/network
                    mail_clean = _clean_mail_segment(mail_segments[0])
                    if mail_clean:
                        net, tier_idx = rx_meta.get(k, (None, None))
                        if net == "in":
                            in_mail_by_tier[tier_idx] = mail_clean
                        elif net == "out":
                            out_mail_by_tier[tier_idx] = mail_clean

        # Build Mail Order RX values from collected tier mail segments in tier order.
        in_mail_values = [in_mail_by_tier[i] for i in range(1, 6) if in_mail_by_tier[i]]
        out_mail_values = [out_mail_by_tier[i] for i in range(1, 6) if out_mail_by_tier[i]]

        if in_mail_values:
            parsed["In-Network Mail Order RX"] = " / ".join(in_mail_values)
        if out_mail_values:
            parsed["Out-of-Network Mail Order RX"] = " / ".join(out_mail_values)

    # Health SBCs often don't state plan-level coinsurance explicitly; infer it
    # from repeated '<number>% coinsurance' patterns in the full PDF text and
    # only use this when the corresponding JSON fields are empty or malformed.
    cat = (category or "").lower()
    if cat in ["health", "health_3tier"]:
        coins = detect_plan_level_coinsurance(dest_pdf_text)
        if coins:
            in_co = coins.get("in_network_coinsurance")
            out_co = coins.get("out_of_network_coinsurance")

            if in_co is not None:
                curr_in = str(parsed.get("In-Network Coinsurance", "") or "").strip()
                if not curr_in or "%" not in curr_in:
                    parsed["In-Network Coinsurance"] = f"{in_co}%"
            if out_co is not None:
                curr_out = str(parsed.get("Out-of-Network Coinsurance", "") or "").strip()
                if not curr_out or "%" not in curr_out:
                    parsed["Out-of-Network Coinsurance"] = f"{out_co}%"
            
            print(f"⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️outofnetwork coinsurance: {out_co}...")
    
    if refine_blanks:
        # Identify fields that are still blank after the main pass
        blank_fields = [k for k in required_keys if not str(parsed.get(k, "")).strip()]

        # Optional logging for debugging
        if blank_fields:
            print(f"⚠️  Main extraction left {len(blank_fields)} blank fields (showing up to 10): {blank_fields[:10]}...")

        # Second-pass refinement: try to fill ALL blank fields using ONLY target PDF text.
        # This prioritizes accuracy over speed and can be more expensive, but greatly
        # improves recall for difficult layouts/fields.
        if blank_fields:
            try:
                parsed = await refine_blank_fields(
                    llm=llm,
                    dest_pdf_text=dest_pdf_text,
                    category=category,
                    initial_json=parsed,
                    blank_fields=blank_fields,
                )
                # Recompute blanks after refinement for logging
                remaining_blanks = [k for k in required_keys if not str(parsed.get(k, "")).strip()]
                if remaining_blanks:
                    print(f"⚠️  After refinement, {len(remaining_blanks)} fields still blank (up to 10): {remaining_blanks[:10]}...")
                else:
                    print("✓ All fields have non-empty values after refinement pass.")
            except Exception as ex:
                print(f"Refinement pass failed: {ex}")

    print("timing total:", round(time.perf_counter() - t0, 3), "sec")
    return parsed


async def ask_llm_extract_only(
    llm,
    sample_pairs,
    dest_pdf_text: str,
    category: str,
    top_k_samples: int = 1,
    use_samples: bool = True,
) -> dict:
    """
    Lightweight extraction call:
    - Builds the same system/user prompts as ask_llm_mapping_logic
    - Calls the LLM and parses JSON
    - Only applies replace_nulls + filter_to_required_keys
    - Does NOT run any additional heuristics/post-processing (RX retail/mail rewrite,
      coinsurance inference, refinement pass, etc.)
    """
    system_prompt = get_cached_system_prompt(category, use_samples=use_samples)

    required_keys = get_required_keys(category)
    num_fields = len(required_keys)

    selected_samples = []
    if use_samples and sample_pairs:
        selected_samples = select_top_k_samples_by_overlap(dest_pdf_text, sample_pairs, k=top_k_samples)
    elif use_samples and not sample_pairs:
        print("Warning: use_samples=True but no sample_pairs provided")

    # Token budgeting (same conservative approach as main function)
    TOKEN_ESTIMATION_RATIO = 34000.0 / 30000.0
    MAX_INPUT_TOKENS_ACTUAL_LLM = 29700
    MAX_INPUT_TOKENS = int(MAX_INPUT_TOKENS_ACTUAL_LLM / TOKEN_ESTIMATION_RATIO)

    system_tokens = estimate_tokens(system_prompt)
    available_tokens = MAX_INPUT_TOKENS - system_tokens - 500

    target_section_header = "TARGET PDF:\n"
    target_header_tokens = estimate_tokens(target_section_header + "\n---\n")
    target_pdf_tokens = estimate_tokens(dest_pdf_text)
    min_tokens_for_target = target_header_tokens + target_pdf_tokens

    user_prompt_parts = []

    # Output budget
    if use_samples:
        max_new_tokens = 512
    else:
        estimated_tokens_needed = num_fields * 50 + 300
        estimated_tokens_needed = int(estimated_tokens_needed * 2 / 3)
        max_new_tokens = max(2000, min(estimated_tokens_needed, 4000))

    used_tokens = 0

    if not use_samples:
        if min_tokens_for_target > available_tokens:
            max_target_tokens = available_tokens - target_header_tokens
            dest_pdf_text = truncate_text_to_token_limit(dest_pdf_text, max_target_tokens)
        user_prompt_parts.append(f"{target_section_header}{dest_pdf_text}\n---\n")
    else:
        tokens_for_samples = 0
        if min_tokens_for_target > available_tokens:
            max_target_tokens = available_tokens - target_header_tokens
            dest_pdf_text = truncate_text_to_token_limit(dest_pdf_text, max_target_tokens)
            selected_samples = []
            tokens_for_samples = 0
        else:
            tokens_for_samples = available_tokens - min_tokens_for_target

        if selected_samples and tokens_for_samples > 1000:
            for i, (s_pdf, s_json) in enumerate(selected_samples):
                oritinal_compact_json = json.dumps(s_json, separators=(",", ":"))
                filtered_json = {
                    k: v for k, v in s_json.items()
                    if v is not None and str(v).strip() != ""
                }
                compact_json = json.dumps(filtered_json, separators=(",", ":"))

                total_chars = len(oritinal_compact_json)
                max_new_tokens = max(max_new_tokens, math.ceil(total_chars * 0.7) + 50)

                remaining_for_samples = tokens_for_samples - used_tokens
                sample_header_template = f"SAMPLE PDF #{i+1}:\n\nSAMPLE JSON #{i+1}:\n{compact_json}\n---\n"
                sample_header_tokens = estimate_tokens(sample_header_template)
                available_for_this_sample = remaining_for_samples - 500 - sample_header_tokens

                if available_for_this_sample < 100:
                    break

                estimated_sample_tokens = estimate_tokens(s_pdf)
                if estimated_sample_tokens > available_for_this_sample:
                    safe_target_tokens = int(available_for_this_sample * 0.9)
                    s_pdf = truncate_text_from_end(s_pdf, safe_target_tokens)

                sample_section = f"SAMPLE PDF #{i+1}:\n{s_pdf}\nSAMPLE JSON #{i+1}:\n{compact_json}\n---\n"
                sample_tokens = estimate_tokens(sample_section)
                if used_tokens + sample_tokens > tokens_for_samples - 500:
                    break

                user_prompt_parts.append(sample_section)
                used_tokens += sample_tokens

        remaining_tokens = available_tokens - used_tokens - target_header_tokens
        if estimate_tokens(dest_pdf_text) > remaining_tokens:
            dest_pdf_text = truncate_text_to_token_limit(dest_pdf_text, remaining_tokens)

        user_prompt_parts.append(f"{target_section_header}{dest_pdf_text}\n---\n")

    user_prompt = "\n".join(user_prompt_parts)
    total_input_tokens = system_tokens + estimate_tokens(user_prompt)
    print(f"[extract_only] Token usage: system={system_tokens}, user_prompt={estimate_tokens(user_prompt)}, total_input={total_input_tokens}, max_new_token: {max_new_tokens}")

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
    parsed = filter_to_required_keys(parsed, required_keys)
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

def validate_out_of_network_extraction(result_json: dict, pdf_text: str, category: str) -> dict:
    """
    Post-process validation: Check if out-of-network values might have been missed.
    Returns a dict with validation info and warnings if suspicious cases are found.
    """
    required_keys = get_required_keys(category)
    
    # Find all out-of-network fields for this category
    out_of_network_fields = [k for k in required_keys if k.startswith("Out-of-Network")]
    
    # If no out-of-network fields for this category, skip validation
    if not out_of_network_fields:
        return {"valid": True, "warnings": []}
    
    # Count how many out-of-network fields are empty/missing
    empty_oon_fields = []
    for field in out_of_network_fields:
        value = result_json.get(field, "")
        if not value or str(value).strip().lower() in ["", "n/a", "na", "none"]:
            empty_oon_fields.append(field)
    
    # If all out-of-network fields are empty, check if PDF text contains out-of-network keywords
    warnings = []
    if len(empty_oon_fields) == len(out_of_network_fields):
        # All OON fields are empty - check if PDF mentions out-of-network
        pdf_lower = pdf_text.lower()
        oon_keywords = [
            "out-of-network", "out of network", 
            "non-network", "non network",
            "non-participating", "non participating",
            "o-o-n", "oon"
        ]
        
        if any(keyword in pdf_lower for keyword in oon_keywords):
            warnings.append(
                "WARNING: All out-of-network fields are empty, but the PDF text contains "
                "out-of-network keywords. Out-of-network values may have been missed."
            )
            print("⚠️  " + warnings[0])
    
    # Check if most OON fields are empty but some in-network fields have values
    elif len(empty_oon_fields) > len(out_of_network_fields) * 0.7:
        # More than 70% of OON fields are empty
        # Check if corresponding in-network fields have values
        in_network_fields_with_values = 0
        for field in out_of_network_fields:
            # Get corresponding in-network field
            in_network_field = field.replace("Out-of-Network", "In-Network")
            in_value = result_json.get(in_network_field, "")
            if in_value and str(in_value).strip().lower() not in ["", "n/a", "na", "none"]:
                in_network_fields_with_values += 1
        
        # If we have many in-network values but few out-of-network values, it might be suspicious
        if in_network_fields_with_values > len(out_of_network_fields) * 0.5:
            warnings.append(
                f"WARNING: {len(empty_oon_fields)}/{len(out_of_network_fields)} out-of-network "
                "fields are empty, but corresponding in-network fields have values. "
                "Please verify that out-of-network information is truly missing from the PDF."
            )
            print("⚠️  " + warnings[0])
    
    return {
        "valid": len(warnings) == 0,
        "warnings": warnings,
        "empty_oon_fields_count": len(empty_oon_fields),
        "total_oon_fields": len(out_of_network_fields)
    }
