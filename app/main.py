import os
from fastapi import FastAPI, File, UploadFile, Form, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import json
import shutil

from . import db
from .extract import pdf_to_text
from .extract import pdf_to_text_with_tables
from .extract_new import extract_pdf_to_string
from .schema import ExtractResp
from .openai_util import ask_gpt_mapping_logic
from .llm_field_batch_refine import refine_result_json_with_batch_llm
from .openai_util import ask_gpt_mapping_logic, filter_to_required_keys, fill_from_matched_sample, replace_nulls
from .category_key_registry import get_required_keys

db.init_sqlite()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.post("/get_pdf")
async def get_pdf(
    file: UploadFile = File(...)
):
    pdf_bytes = await file.read()
    text = pdf_to_text_with_tables(pdf_bytes)
    with open("result.md", "w", encoding="utf-8") as f:
        f.write(text)  # your PDF->text output

    return text

@app.post("/extract_json")
async def extract_json_endpoint(
    file: UploadFile = File(...),
    category: str = Form(...)
):
    pdf_bytes = await file.read()
    # Search for top_K similar samples instead of just 1
    sims = db.search_similar_pdf(category.lower(), pdf_bytes, top_k=2)   # Get 2 for few-shot!
    if not sims:
        return JSONResponse(
            status_code=400,
            content={"error": "No similar samples in DB. Please upload at least 1 sample first with /sample/add_one."}
        )

    # Build the `(sample_pdf_text, sample_json)` pairs for few-shot
    sample_pairs = []
    for s in sims:
        sample_pdf_text = pdf_to_text(open(s['pdf_path'], 'rb').read())
        sample_json = s['json_data']
        sample_pairs.append((sample_pdf_text, sample_json))

    dest_pdf_text = pdf_to_text(pdf_bytes)
    # print(f"des pdf to text is:\n {dest_pdf_text}")

    # Call few-shot LLM mapping logic
    result_json = ask_gpt_mapping_logic(
        sample_pairs=sample_pairs,
        dest_pdf_text=dest_pdf_text,
        category=category
    )

    # Strictly filter to expected keys
    required_keys = get_required_keys(category)
    cleaned_result_json = filter_to_required_keys(result_json, required_keys)

    # Fill from best sample for likely-shared fields
    best_sample = sims[0]['json_data']
    cleaned_result_json = fill_from_matched_sample(cleaned_result_json, best_sample)

    # Replace None/null with ""
    cleaned_result_json = replace_nulls(cleaned_result_json)

    # ADD THIS BLOCK
    # cleaned_result_json, updated_fields = refine_result_json_with_batch_llm(cleaned_result_json, dest_pdf_text)
    # print("Fields updated by batch LLM:", updated_fields)

    matched_plan = best_sample.get('Plan Name', '')

    # return cleaned_result_json
    return {
        "result_json": cleaned_result_json,
        "matched_sample_plan": matched_plan,
        "matched_json1": sims[0]['json_data']
        # "matched_json2": sims[1]['json_data'],
        # "matched_json3": sims[2]['json_data']
    }

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/extract_json_new")
async def extract_json_endpoint_new(
    file: UploadFile = File(...),
    category: str = Form(...)
):
    pdf_bytes = await file.read()
    print(f"testsetstset: {pdf_bytes}")
    # Save uploaded PDF to disk
    pdf_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # --- Step 1: Extract text (with tables) as string ---
    extracted = extract_pdf_to_string(pdf_path)
    dest_pdf_text = extracted["content"]
    # print(f"Extracted PDF text (with tables):\n{dest_pdf_text}")

    # --- Step 2: Search for top_k similar samples in DB ---
    sims = db.search_similar_pdf(category.lower(), pdf_bytes, top_k=1)  # assumes DB can work with path
    if not sims:
        return JSONResponse(
            status_code=400,
            content={"error": "No similar samples in DB. Please upload at least 1 sample first with /sample/add_one."}
        )

    # --- Step 3: Build few-shot sample pairs ---
    sample_pairs = []
    for s in sims:
        sample_extracted = extract_pdf_to_string(s['pdf_path'])
        sample_pdf_text = sample_extracted["content"]
        sample_json = s['json_data']
        sample_pairs.append((sample_pdf_text, sample_json))

    # --- Step 4: Call few-shot LLM mapping logic ---
    result_json = ask_gpt_mapping_logic(
        sample_pairs=sample_pairs,
        dest_pdf_text=dest_pdf_text,
        category=category
    )

    # --- Step 5: Strictly filter to expected keys ---
    required_keys = get_required_keys(category)
    cleaned_result_json = filter_to_required_keys(result_json, required_keys)

    # --- Step 6: Fill likely-shared fields from best sample ---
    best_sample = sims[0]['json_data']
    cleaned_result_json = fill_from_matched_sample(cleaned_result_json, best_sample)

    # --- Step 7: Replace None/null with empty string ---
    cleaned_result_json = replace_nulls(cleaned_result_json)

    # Optional: refine_result_json_with_batch_llm (commented out)
    # cleaned_result_json, updated_fields = refine_result_json_with_batch_llm(cleaned_result_json, dest_pdf_text)
    # print("Fields updated by batch LLM:", updated_fields)

    matched_plan = best_sample.get('Plan Name', '')

    return {
        "result_json": cleaned_result_json,
        "matched_sample_plan": matched_plan,
        "matched_json1": sims[0]['json_data']
        # "matched_json2": sims[1]['json_data'],
        # "matched_json3": sims[2]['json_data']
    }

@app.post("/sample/add_one")
async def add_sample_endpoint(
      pdf_file: UploadFile = File(...),
      json_file: UploadFile = File(...),
      category: str = Form(...)
):
    import hashlib
    pdf_bytes = await pdf_file.read()
    json_bytes = await json_file.read()
    json_data = json.loads(json_bytes.decode())

    # Exact deduplication: check for identical PDF by hash
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    import sqlite3
    conn = sqlite3.connect(db.SQLITE_METADATA)
    c = conn.cursor()
    c.execute('SELECT pdf_path FROM samples')
    existing_paths = [row[0] for row in c.fetchall()]
    conn.close()
    is_duplicate = False
    for path in existing_paths:
        try:
            with open(path, "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() == pdf_hash:
                    is_duplicate = True
                    break
        except Exception:
            continue

    if is_duplicate:
        return {"status": "duplicate", "reason": "An identical PDF already exists in the database."}

    sample_id = db.add_sample_to_db(category.lower(), pdf_bytes, json_data)
    return {"status": "ok", "sample_id": sample_id}

@app.post("/sample/add_batch")
async def add_batch_endpoint(folder_path: str = Body(...), category: str = Body(...)):
    try:
        files = os.listdir(folder_path)
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid directory: {str(e)}"}
        )

    pdf_files = [f for f in files if f.lower().endswith(".pdf")]
    results = []

    import hashlib
    import sqlite3
    # Preload all existing PDF hashes for efficiency
    conn = sqlite3.connect(db.SQLITE_METADATA)
    c = conn.cursor()
    c.execute('SELECT pdf_path FROM samples')
    existing_paths = [row[0] for row in c.fetchall()]
    conn.close()
    existing_hashes = set()
    for path in existing_paths:
        try:
            with open(path, "rb") as f:
                existing_hashes.add(hashlib.sha256(f.read()).hexdigest())
        except Exception:
            continue

    for pdf_file in pdf_files:
        stem = os.path.splitext(pdf_file)[0]
        json_file = stem + ".json"
        pdf_path = os.path.join(folder_path, pdf_file)
        json_path = os.path.join(folder_path, json_file)
        if not os.path.exists(json_path):
            results.append({"pdf_file": pdf_file, "status": "error", "reason": "No matching JSON file"})
            continue
        try:
            with open(pdf_path, "rb") as pf:
                pdf_bytes = pf.read()
            pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
            if pdf_hash in existing_hashes:
                results.append({"pdf_file": pdf_file, "status": "duplicate", "reason": "An identical PDF already exists in the database."})
                continue
            with open(json_path, "r", encoding="utf-8") as jf:
                json_data = json.load(jf)
            sample_id = db.add_sample_to_db(category.lower(), pdf_bytes, json_data)
            results.append({"pdf_file": pdf_file, "status": "ok", "sample_id": sample_id})
            existing_hashes.add(pdf_hash)  # Add to set to prevent duplicates within the batch
        except Exception as e:
            results.append({"pdf_file": pdf_file, "status": "error", "reason": str(e)})
    return {
        "processed": len(pdf_files),
        "successes": sum(r["status"] == "ok" for r in results),
        "failures": [r for r in results if r["status"] != "ok"],
        "results": results
    }


@app.get("/")
def root():
    return {"msg": "OK"}
