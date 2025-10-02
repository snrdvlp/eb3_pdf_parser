import os
import json
import shutil
import time
import asyncio
import hashlib
import sqlite3

from . import db
from fastapi import FastAPI, File, UploadFile, Form, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from .extract import pdf_to_text
from .extract import pdf_to_text_with_tables
from .category_key_registry import get_required_keys
from .my_llm import RemoteLLM
from .my_llm_util import ask_llm_mapping_logic, filter_to_required_keys, replace_nulls

MAX_PDF_THREADS = 4  # tune for your CPU and disk

semaphore = asyncio.Semaphore(MAX_PDF_THREADS)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Loads health llm model
llm = RemoteLLM()

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
    start = time.perf_counter()
    temp = start

    # Read PDF file bytes (already async)
    pdf_bytes = await file.read()

    # Run PDF → text in threadpool
    dest_pdf_text = await asyncio.to_thread(pdf_to_text, pdf_bytes)

    # Search vector DB (already fast, leave sync unless heavy)
    sims = db.search_similar_pdf(category.lower(), dest_pdf_text, top_k=1)
    if not sims:
        return JSONResponse(
            status_code=400,
            content={"error": "No similar samples in DB. Please upload at least 1 sample first with /sample/add_one."}
        )

    print(f"Elapsed time for searching similar pdf: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    # Load sample PDFs concurrently
    async def load_sample(s):
        pdf_bytes = await asyncio.to_thread(lambda: open(s['pdf_path'], "rb").read())
        sample_pdf_text = await asyncio.to_thread(pdf_to_text, pdf_bytes)
        return (sample_pdf_text, s['json_data'])

    sample_pairs = await asyncio.gather(*(load_sample(s) for s in sims))

    print(f"Elapsed time for extracting pdf to string: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    # Call LLM mapping logic (which itself calls async llm.chat now)
    result_json = await ask_llm_mapping_logic(
        llm,
        sample_pairs,
        dest_pdf_text,
        category,
    )

    print(f"Elapsed time for llm api call: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    # Post-processing
    required_keys = get_required_keys(category)
    cleaned_result_json = filter_to_required_keys(result_json, required_keys)
    cleaned_result_json = replace_nulls(cleaned_result_json)

    best_sample = sims[0]['json_data']
    matched_plan = best_sample.get('Plan Name', '')

    print(f"Elapsed time for total process: {time.perf_counter() - start:.2f} seconds")

    return cleaned_result_json
    return {
        "result_json": cleaned_result_json,
        "matched_sample_plan": matched_plan,
        "matched_json1": sims[0]['json_data'],
        # "matched_json2": sims[1]['json_data']
    }

@app.post("/extract_json_with_similar")
async def extract_json_endpoint_with_similar(
    file: UploadFile = File(...),
    category: str = Form(...)
):
    start = time.perf_counter()
    temp = start

    # Read PDF file bytes (already async)
    pdf_bytes = await file.read()

    # Run PDF → text in threadpool
    dest_pdf_text = await asyncio.to_thread(pdf_to_text, pdf_bytes)

    # Search vector DB (already fast, leave sync unless heavy)
    sims = db.search_similar_pdf(category.lower(), dest_pdf_text, top_k=1)
    if not sims:
        return JSONResponse(
            status_code=400,
            content={"error": "No similar samples in DB. Please upload at least 1 sample first with /sample/add_one."}
        )

    print(f"Elapsed time for searching similar pdf: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    # Load sample PDFs concurrently
    async def load_sample(s):
        async with semaphore:
            pdf_bytes = await asyncio.to_thread(lambda: open(s['pdf_path'], "rb").read())
            sample_pdf_text = await asyncio.to_thread(pdf_to_text, pdf_bytes)
            return (sample_pdf_text, s['json_data'])

    sample_pairs = await asyncio.gather(*(load_sample(s) for s in sims))

    print(f"Elapsed time for extracting pdf to string: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    # Call LLM mapping logic (which itself calls async llm.chat now)
    result_json = await ask_llm_mapping_logic(
        llm,
        sample_pairs,
        dest_pdf_text,
        category,
    )

    print(f"Elapsed time for llm api call: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    # Post-processing
    required_keys = get_required_keys(category)
    cleaned_result_json = filter_to_required_keys(result_json, required_keys)
    cleaned_result_json = replace_nulls(cleaned_result_json)

    best_sample = sims[0]['json_data']
    matched_plan = best_sample.get('Plan Name', '')

    print(f"Elapsed time for total process: {time.perf_counter() - start:.2f} seconds")

    return {
        "result_json": cleaned_result_json,
        "matched_sample_plan": matched_plan,
        "matched_json1": sims[0]['json_data'],
        # "matched_json2": sims[1]['json_data']
    }

@app.post("/sample/add_one")
async def add_sample_endpoint(
      pdf_file: UploadFile = File(...),
      json_file: UploadFile = File(...),
      category: str = Form(...)
):
    pdf_bytes = await pdf_file.read()
    json_bytes = await json_file.read()
    json_data = json.loads(json_bytes.decode())

    # Initialize db by category
    db.init_sqlite(category)

    # Exact deduplication: check for identical PDF by hash
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    
    paths = db._get_category_paths(category)
    conn = sqlite3.connect(paths["sqlite"])
    c = conn.cursor()
    
    # Check if sample exists
    c.execute('SELECT id, pdf_path FROM samples WHERE pdf_hash=?', (pdf_hash,))
    row = c.fetchone()
    
    if row:
        sample_id, old_pdf_path = row
        
        # Overwrite PDF file on disk
        pdf_path = os.path.join(paths["cat_dir"], old_pdf_path)
        with open(pdf_path, "wb") as pf:
            pf.write(pdf_bytes)
        
        # Update metadata
        c.execute(
            'UPDATE samples SET category=?, carrier=?, plan=?, json_data=? WHERE id=?',
            (
                category.lower(),
                json_data.get('Carrier Name', ''),
                json_data.get('Plan Name', ''),
                json.dumps(json_data),
                sample_id
            )
        )
        conn.commit()
        conn.close()
        return {"status": "updated", "sample_id": sample_id}

    # If not duplicate, insert new
    sample_id = db.add_sample_to_db(category.lower(), pdf_bytes, json_data, pdf_hash)
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

    # Initialize db by category
    db.init_sqlite(category)

    # Preload all existing PDF hashes for efficiency
    paths = db._get_category_paths(category)
    conn = sqlite3.connect(paths["sqlite"])
    
    c = conn.cursor()
    c.execute('SELECT pdf_hash FROM samples')
    existing_hashes = {row[0] for row in c.fetchall()}
    conn.close()

    for pdf_file in pdf_files:
        stem = os.path.splitext(pdf_file)[0]
        json_file = stem + ".json"

        pdf_path = os.path.join(folder_path, pdf_file)
        json_path = os.path.join(folder_path, json_file)

        if not os.path.exists(json_path):
            results.append({
                "pdf_file": pdf_file,
                "status": "error",
                "reason": "No matching JSON file"
            })
            continue

        try:
            # Read PDF + compute hash
            with open(pdf_path, "rb") as pf:
                pdf_bytes = pf.read()
            pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()

            # Check for duplicate
            if pdf_hash in existing_hashes:
                results.append({
                    "pdf_file": pdf_file,
                    "status": "duplicate",
                    "reason": "An identical PDF already exists in the database."
                })
                continue

            # Read JSON
            with open(json_path, "r", encoding="utf-8") as jf:
                json_data = json.load(jf)

            # Add to DB
            sample_id = db.add_sample_to_db(category.lower(), pdf_bytes, json_data, pdf_hash)
            results.append({
                "pdf_file": pdf_file,
                "status": "ok",
                "sample_id": sample_id
            })
            existing_hashes.add(pdf_hash)  # Prevent dupes in same batch

        except Exception as e:
            results.append({
                "pdf_file": pdf_file,
                "status": "error",
                "reason": str(e)
            })

    return {
        "processed": len(pdf_files),
        "successes": sum(r["status"] == "ok" for r in results),
        "failures": [r for r in results if r["status"] != "ok"],
        "results": results
    }