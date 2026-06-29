import os
import json
import shutil
import time
import asyncio
import hashlib
import sqlite3
import numpy as np
import faiss
import logging
from logging.handlers import RotatingFileHandler

from .embedder import get_embedding
from . import db
from fastapi import FastAPI, File, UploadFile, Form, Body, Depends, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import json as json_lib
from typing import List
from .extract import pdf_to_text, pdf_to_text_with_tables, pdf_to_text_ocr
from .category_key_registry import get_required_keys
from .my_llm import RemoteLLM
from .my_llm_util import ask_llm_mapping_logic, ask_llm_extract_only, filter_to_required_keys, replace_nulls, validate_out_of_network_extraction, SIMILARITY_THRESHOLD
from .auth import get_api_key

# Prometheus imports
from prometheus_client import Counter, Histogram, Gauge, generate_latest, start_http_server
import multiprocessing

# ==========================================
# Logging Configuration
# ==========================================
LOG_DIR = os.getenv("LOG_DIR", "/var/log/pdf-parser")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# Create log directory if it doesn't exist (will need permissions on server)
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except PermissionError:
    # Fallback to local logs if can't write to /var/log
    LOG_DIR = "./logs"
    LOG_FILE = os.path.join(LOG_DIR, "app.log")
    os.makedirs(LOG_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        # Rotating file handler - max 50MB per file, keep 5 backup files
        RotatingFileHandler(LOG_FILE, maxBytes=50*1024*1024, backupCount=5),
        # Also log to console
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("pdf_parser")
logger.info(f"Logging initialized. Log file: {LOG_FILE}")

MAX_PDF_THREADS = 20  # tune for your CPU and disk

semaphore = asyncio.Semaphore(MAX_PDF_THREADS)

app = FastAPI()

# Start Prometheus metrics server on port 9265 (internal monitoring only)
# This runs on localhost and Nebula interface, not exposed to public internet
start_http_server(9265, addr='0.0.0.0')  # Neal will handle firewall rules
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Exception handler for JSON parsing errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    error_msg = "Validation error"
    
    # Check if it's a JSON parsing error
    for error in errors:
        if error.get("type") == "json_invalid":
            ctx = error.get("ctx", {})
            if "Invalid \\escape" in str(ctx.get("error", "")):
                error_msg = (
                    "Invalid JSON: Windows paths with backslashes must be escaped. "
                    "Use double backslashes (\\\\ or use forward slashes (/). "
                    "Example: 'C:\\\\Users\\\\folder' or 'C:/Users/folder'"
                )
            else:
                error_msg = f"Invalid JSON: {ctx.get('error', 'Unknown JSON error')}"
            break
    
    return JSONResponse(
        status_code=422,
        content={
            "error": error_msg,
            "detail": errors
        }
    )

# ==========================================
# Prometheus Metrics Setup
# ==========================================
REQUEST_COUNT = Counter(
    'pdf_parser_requests_total', 
    'Total number of requests',
    ['method', 'endpoint']
)

REQUEST_DURATION = Histogram(
    'pdf_parser_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint']
)

ACTIVE_REQUESTS = Gauge(
    'pdf_parser_active_requests',
    'Number of active requests'
)

REQUEST_SIZE = Histogram(
    'pdf_parser_request_size_bytes',
    'Request size in bytes',
    ['endpoint']
)

# Prometheus middleware for tracking requests
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    # Increment active requests
    ACTIVE_REQUESTS.inc()
    
    method = request.method
    endpoint = request.url.path
    
    # Time the request
    start_time = time.perf_counter()
    
    try:
        response = await call_next(request)
    finally:
        duration = time.perf_counter() - start_time
        
        # Record metrics
        REQUEST_COUNT.labels(method=method, endpoint=endpoint).inc()
        REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)
        ACTIVE_REQUESTS.dec()
    
    return response

# Loads health llm model
llm = RemoteLLM()

# ==========================================
# Helper Functions
# ==========================================
def update_sample_in_db(category: str, sample_id: str, pdf_bytes: bytes, json_data: dict, paths: dict, conn: sqlite3.Connection) -> bool:
    """
    Helper function to update an existing sample in the database.
    Updates text file, metadata, and rebuilds FAISS index.
    Returns True if successful, False otherwise.
    """
    try:
        c = conn.cursor()
        
        # Get existing pdf_path
        c.execute('SELECT pdf_path FROM samples WHERE id=?', (sample_id,))
        row = c.fetchone()
        if not row:
            logger.warning(f"Sample {sample_id} not found in database")
            return False
        
        old_pdf_path = row[0]
        
        logger.info(f"Updating existing sample: {sample_id}")
        
        # Parse PDF to text
        text = pdf_to_text(pdf_bytes)
        
        # Overwrite text file on disk
        txt_path = os.path.join(paths["cat_dir"], old_pdf_path)
        try:
            with open(txt_path, "w", encoding="utf-8") as tf:
                tf.write(text)
        except Exception as e:
            logger.error(f"Failed to write file {txt_path}: {e}")
            raise
        
        # Also persist original raw PDF alongside the txt file.
        raw_pdf_filename = f"{sample_id}.pdf"
        raw_pdf_path = os.path.join(paths["cat_dir"], raw_pdf_filename)
        try:
            with open(raw_pdf_path, "wb") as pf:
                pf.write(pdf_bytes)
        except Exception as e:
            logger.error(f"Failed to write raw PDF file {raw_pdf_path}: {e}")
            raise

        # Update metadata
        c.execute(
            'UPDATE samples SET category=?, carrier=?, plan=?, json_data=?, raw_pdf_path=? WHERE id=?',
            (
                category.lower(),
                json_data.get('Carrier Name', ''),
                json_data.get('Plan Name', ''),
                json.dumps(json_data),
                raw_pdf_filename,
                sample_id
            )
        )
        
        # Rebuild FAISS index with updated embedding
        with open(paths["faiss_ids"], "r", encoding="utf-8") as f:
            faiss_ids = [line.strip() for line in f.readlines()]
        
        try:
            sample_index = faiss_ids.index(sample_id)
            
            # Generate new embedding
            new_emb = np.array(get_embedding(text), dtype=np.float32)
            
            # Read all existing samples and rebuild embeddings
            logger.info(f"Rebuilding FAISS index to update sample {sample_id}...")
            
            all_embeddings = []
            for idx, sid in enumerate(faiss_ids):
                if idx == sample_index:
                    # Use new embedding for the updated sample
                    all_embeddings.append(new_emb)
                    logger.debug(f"  Updated embedding at position {idx}")
                else:
                    # Read existing sample text and re-generate embedding
                    c.execute('SELECT pdf_path FROM samples WHERE id=?', (sid,))
                    sample_row = c.fetchone()
                    if sample_row:
                        sample_txt_path = os.path.join(paths["cat_dir"], sample_row[0])
                        with open(sample_txt_path, "r", encoding="utf-8") as stf:
                            sample_txt = stf.read()
                        sample_emb = np.array(get_embedding(sample_txt), dtype=np.float32)
                        all_embeddings.append(sample_emb)
            
            # Rebuild FAISS index with all embeddings
            if all_embeddings:
                embeddings_matrix = np.array(all_embeddings, dtype=np.float32)
                new_index = faiss.IndexFlatL2(embeddings_matrix.shape[1])
                new_index.add(embeddings_matrix)
                faiss.write_index(new_index, paths["vector_db"])
                logger.info(f"✓ FAISS index rebuilt with {len(all_embeddings)} samples")
            
            return True
            
        except ValueError:
            logger.warning(f"Sample {sample_id} not found in FAISS index")
            return False
        except Exception as e:
            logger.error(f"Error updating embedding: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Error updating sample {sample_id}: {e}")
        return False

@app.post("/get_pdf")
async def get_pdf(
    file: UploadFile = File(...),
    api_key: str = Depends(get_api_key)
):
    pdf_bytes = await file.read()
    text = pdf_to_text(pdf_bytes)
    with open("result.md", "w", encoding="utf-8") as f:
        f.write(text)  # your PDF->text output

    return text

@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(), media_type="text/plain")

@app.get("/health")
def health_check():
    """Health check endpoint for monitoring - returns 200 if service is running"""
    return {"status": "healthy", "service": "pdf-parser"}

@app.post("/extract_json")
async def extract_json_endpoint(
    file: UploadFile = File(...),
    category: str = Form(...),
    api_key: str = Depends(get_api_key)
):
    start = time.perf_counter()
    temp = start

    # Read PDF file bytes (already async)
    pdf_bytes = await file.read()
    async with semaphore:
        dest_pdf_text = await asyncio.to_thread(pdf_to_text, pdf_bytes)

    logger.info(f"PDF extraction completed in {time.perf_counter() - temp:.2f}s")
    temp = time.perf_counter()

    # Search vector DB (already fast, leave sync unless heavy)
    sims = db.search_similar_pdf(category.lower(), dest_pdf_text)
    if not sims:
        logger.warning(f"No similar samples found for category: {category}")
        return JSONResponse(
            status_code=400,
            content={"error": "No similar samples in DB. Please upload at least 1 sample first with /sample/add_one."}
        )

    logger.info(f"Similar PDF search completed in {time.perf_counter() - temp:.2f}s")
    temp = time.perf_counter()

    best_distance = sims[0].get('distance', None)
    logger.info(f"Best match distance: {best_distance}")
    
    # If exact match, skip LLM and use matched sample JSON
    if best_distance == -1.0:
        logger.info(f"Exact match found - using cached result")
        result_json = sims[0]['json_data']
    else:
        # Check if distance is below threshold to use samples
        use_samples = best_distance is not None and best_distance < SIMILARITY_THRESHOLD
        
        if use_samples:
            logger.info(f"Distance {best_distance} < threshold {SIMILARITY_THRESHOLD} - using samples in LLM prompt")
            # Load sample PDFs concurrently
            async def load_sample(s):
                with open(s['txt_path'], "r", encoding="utf-8") as tf:
                    sample_pdf_text = tf.read()
                return (sample_pdf_text, s['json_data'])

            sample_pairs = await asyncio.gather(*(load_sample(s) for s in sims))
        else:
            logger.info(f"Distance {best_distance} >= threshold {SIMILARITY_THRESHOLD} - extracting without samples")
            sample_pairs = []

        # print(f"Elapsed time for extracting pdf to string: {time.perf_counter() - temp:.2f} seconds")
        temp = time.perf_counter()

        # Call LLM mapping logic (which itself calls async llm.chat now)
        result_json = await ask_llm_mapping_logic(
            llm,
            sample_pairs,
            dest_pdf_text,
            category,
            use_samples=use_samples,
            refine_blanks=False,  # set to False to disable second-pass refinement
        )

        logger.info(f"LLM extraction completed in {time.perf_counter() - temp:.2f}s")
        temp = time.perf_counter()
        
        # Post-process validation: Check for potentially missed out-of-network values
        validation_result = validate_out_of_network_extraction(result_json, dest_pdf_text, category)
        if not validation_result["valid"]:
            logger.warning(f"Validation warnings: {validation_result['warnings']}")

    logger.info(f"Total extraction process completed in {time.perf_counter() - start:.2f}s")

    return result_json

@app.post("/extract_json_with_similar")
async def extract_json_endpoint_with_similar(
    file: UploadFile = File(...),
    category: str = Form(...),
    api_key: str = Depends(get_api_key)
):
    start = time.perf_counter()
    temp = start

    # Read PDF file bytes (already async)
    pdf_bytes = await file.read()
    async with semaphore:
        dest_pdf_text = await asyncio.to_thread(pdf_to_text, pdf_bytes)

    print(f"Elapsed time for semaphore: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    # Search vector DB (already fast, leave sync unless heavy)
    sims = db.search_similar_pdf(category.lower(), dest_pdf_text)
    if not sims:
        return JSONResponse(
            status_code=400,
            content={"error": "No similar samples in DB. Please upload at least 1 sample first with /sample/add_one."}
        )

    print(f"Elapsed time for searching similar pdf: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    best_distance = sims[0].get("distance", None)
    print(f"distance is : {best_distance}")
    
    # If exact match, skip LLM and use matched sample JSON
    if best_distance == -1.0:
        print(f"exact match\n{sims[0]}")
        result_json = sims[0]['json_data']
    else:
        # Check if distance is below threshold to use samples
        use_samples = best_distance is not None and best_distance < SIMILARITY_THRESHOLD
        
        if use_samples:
            print(f"Distance {best_distance} < threshold {SIMILARITY_THRESHOLD} - using samples in LLM prompt")
            # Load sample PDFs concurrently
            async def load_sample(s):
                with open(s['txt_path'], "r", encoding="utf-8") as tf:
                    sample_pdf_text = tf.read()
                return (sample_pdf_text, s['json_data'])

            sample_pairs = await asyncio.gather(*(load_sample(s) for s in sims))
        else:
            print(f"Distance {best_distance} >= threshold {SIMILARITY_THRESHOLD} - extracting without samples")
            sample_pairs = []

        # print(f"Elapsed time for extracting pdf to string: {time.perf_counter() - temp:.2f} seconds")
        temp = time.perf_counter()

        # Call LLM mapping logic (which itself calls async llm.chat now)
        result_json = await ask_llm_mapping_logic(
            llm,
            sample_pairs,
            dest_pdf_text,
            category,
            use_samples=use_samples,
            refine_blanks=False,  # set to False to disable second-pass refinement
        )

        print(f"Elapsed time for llm api call: {time.perf_counter() - temp:.2f} seconds")
        temp = time.perf_counter()
        
        # Post-process validation: Check for potentially missed out-of-network values
        validation_result = validate_out_of_network_extraction(result_json, dest_pdf_text, category)
        if not validation_result["valid"]:
            print(f"Validation warnings: {validation_result['warnings']}")

    best_sample = sims[0]['json_data']
    matched_plan = best_sample.get('Plan Name', '')

    print(f"Elapsed time for total process: {time.perf_counter() - start:.2f} seconds")

    return {
        "result_json": result_json,
        "matched_sample_plan": matched_plan,
        "matched_json1": sims[0]['json_data']
    }

@app.post("/extract_json_ocr")
async def extract_json_ocr_endpoint(
    file: UploadFile = File(...),
    category: str = Form(...),
    api_key: str = Depends(get_api_key)
):
    """
    Extraction endpoint that forces OCR-based PDF parsing (pdf_to_text_ocr),
    bypassing the text/table-based extractor. Everything else (similar search,
    LLM mapping, validation) stays the same as /extract_json.
    """
    start = time.perf_counter()
    temp = start

    # Read PDF file bytes (already async)
    pdf_bytes = await file.read()
    async with semaphore:
        dest_pdf_text = await asyncio.to_thread(pdf_to_text_ocr, pdf_bytes)

    logger.info(f"PDF OCR extraction completed in {time.perf_counter() - temp:.2f}s")
    temp = time.perf_counter()

    # Search vector DB
    sims = db.search_similar_pdf(category.lower(), dest_pdf_text)
    if not sims:
        logger.warning(f"No similar samples found for category (OCR): {category}")
        return JSONResponse(
            status_code=400,
            content={"error": "No similar samples in DB. Please upload at least 1 sample first with /sample/add_one."}
        )

    logger.info(f"Similar PDF search (OCR) completed in {time.perf_counter() - temp:.2f}s")
    temp = time.perf_counter()

    best_distance = sims[0].get('distance', None)
    logger.info(f"[OCR] Best match distance: {best_distance}")

    # If exact match, skip LLM and use matched sample JSON
    if best_distance == -1.0:
        logger.info(f"[OCR] Exact match found - using cached result")
        result_json = sims[0]['json_data']
    else:
        # Check if distance is below threshold to use samples
        use_samples = best_distance is not None and best_distance < SIMILARITY_THRESHOLD

        if use_samples:
            logger.info(f"[OCR] Distance {best_distance} < threshold {SIMILARITY_THRESHOLD} - using samples in LLM prompt")

            async def load_sample(s):
                with open(s['txt_path'], "r", encoding="utf-8") as tf:
                    sample_pdf_text = tf.read()
                return (sample_pdf_text, s['json_data'])

            sample_pairs = await asyncio.gather(*(load_sample(s) for s in sims))
        else:
            logger.info(f"[OCR] Distance {best_distance} >= threshold {SIMILARITY_THRESHOLD} - extracting without samples")
            sample_pairs = []

        temp = time.perf_counter()

        # Call LLM mapping logic
        result_json = await ask_llm_mapping_logic(
            llm,
            sample_pairs,
            dest_pdf_text,
            category,
            use_samples=use_samples,
            refine_blanks=False,
        )

        logger.info(f"[OCR] LLM extraction completed in {time.perf_counter() - temp:.2f}s")
        temp = time.perf_counter()

        # Post-process validation: Check for potentially missed out-of-network values
        validation_result = validate_out_of_network_extraction(result_json, dest_pdf_text, category)
        if not validation_result["valid"]:
            logger.warning(f"[OCR] Validation warnings: {validation_result['warnings']}")

    logger.info(f"[OCR] Total extraction process completed in {time.perf_counter() - start:.2f}s")

    return result_json


async def repair_pdf_markdown(llm, raw_markdown: str, max_new_tokens: int = 4000) -> str:
    """
    Shared LLM-based repair for table+text markdown extracted from SBC PDFs.
    Used by both `/repair_pdf_text` and `/extract_json_v2`.
    """
    system_prompt = """
You are a PDF benefits table repair engine.

You receive markdown text generated from an insurance Summary of Benefits and Coverage (SBC) PDF.
The markdown has TWO kinds of content:
- "### Table (Page X)" sections: markdown tables extracted from the PDF.
- Plain text blocks: flattened text from the same pages.

The table extraction is often structurally incorrect:
- Multi-line cells are split across several rows.
- Text that belongs to one cell may appear in multiple rows or columns.
- Some columns may be misaligned.

The plain text blocks are closer to the true content but lack explicit row/column structure.

Your job is to REPAIR and CONSOLIDATE this information into a cleaner, more accurate text representation
that will be used as input for a downstream benefits extractor.

Guiding principles:
- Use the TABLES as layout hints only (which services/benefits align with which columns).
- Trust the PLAIN TEXT for actual numeric values and phrases (copays, coinsurance, deductibles, etc.).
- When there is a conflict between table and text, ALWAYS trust the plain text.

Metadata preservation:
- The PDF often contains important plan metadata such as:
  * Carrier/insurance company name
  * Plan name
  * Network type and network name
  * Plan year
  * Member website URL
  * Customer service phone number
- If any of this metadata appears anywhere in the input markdown (in tables, headers, or text blocks),
  you MUST preserve it in the cleaned output. Do NOT drop or summarize it away.
  It is acceptable to move it to a more convenient location (e.g., a short metadata section at the top),
  but the actual values MUST still be present verbatim somewhere in the cleaned text.

Output requirements:
- Produce a cleaned markdown text where:
  * Each benefit row (e.g., "Preferred brand drugs", "Imaging (CT/PET scans, MRIs)") is clearly represented once.
  * In-network and out-of-network values for that row appear together on the same logical line or paragraph.
  * RX tiers and mail-order vs retail are preserved as they appear in the plain text.
- Do NOT invent new values; only use values that appear in the input.
- Preserve as much original wording as possible, just fix structural issues (wrong splits, wrong row breaks, misplaced phrases).
- The output should still be human-readable markdown, but it does NOT need to be a perfect markdown table.
""".strip()

    user_prompt = f"""
Here is the raw extracted markdown from the PDF:

---------------- RAW MARKDOWN START ----------------
{raw_markdown}
---------------- RAW MARKDOWN END ----------------

Please return ONLY the cleaned, consolidated markdown text.
Do not add explanations or comments.
""".strip()

    return await llm.chat(system_prompt, user_prompt, max_new_tokens=max_new_tokens)


@app.post("/repair_pdf_text")
async def repair_pdf_text_endpoint(
    file: UploadFile = File(...),
    api_key: str = Depends(get_api_key)
):
    """
    Pre-processing endpoint.

    1. Runs pdf_to_text_with_tables to get combined table + text markdown.
    2. Sends that markdown to the LLM with a specialized prompt that:
       - Treats the '### Table (Page X)' sections as layout hints only.
       - Treats the plain text blocks as the authoritative source of values.
       - Asks the LLM to output a cleaned, consolidated text representation
         suitable for downstream extraction.
    3. Returns the cleaned text.
    """
    start = time.perf_counter()

    pdf_bytes = await file.read()
    # Run heavy PDF processing off the event loop
    raw_markdown = await asyncio.to_thread(pdf_to_text_with_tables, pdf_bytes)
    cleaned = await repair_pdf_markdown(llm, raw_markdown, max_new_tokens=4000)

    logger.info(f"PDF repair completed in {time.perf_counter() - start:.2f}s")

    return cleaned


@app.post("/extract_json_v2")
async def extract_json_v2_endpoint(
    file: UploadFile = File(...),
    category: str = Form(...),
    api_key: str = Depends(get_api_key)
):
    """
    Improved extraction endpoint that:
    1. Runs pdf_to_text_with_tables to get combined table+text markdown.
    2. Uses the LLM (repair_pdf_text logic) to clean and consolidate that markdown,
       leaning on the plain text blocks as authoritative.
    3. Uses the repaired text as dest_pdf_text for the normal extraction flow
       (similarity search + ask_llm_mapping_logic).
    """
    start = time.perf_counter()
    temp = start

    # Read PDF file bytes (already async)
    pdf_bytes = await file.read()

    # Step 1: get raw markdown with tables + text
    async with semaphore:
        raw_markdown = await asyncio.to_thread(pdf_to_text_with_tables, pdf_bytes)

    logger.info(f"[v2] pdf_to_text_with_tables completed in {time.perf_counter() - temp:.2f}s")
    temp = time.perf_counter()

    # Step 2: repair/clean the markdown using the same logic as /repair_pdf_text
    repaired_text = await repair_pdf_markdown(llm, raw_markdown, max_new_tokens=4000)

    logger.info(f"[v2] PDF repair LLM completed in {time.perf_counter() - temp:.2f}s")
    temp = time.perf_counter()

    # Use repaired_text as dest_pdf_text for the normal extraction flow
    dest_pdf_text = repaired_text

    # Step 3: similarity search ONLY to detect exact matches.
    sims = db.search_similar_pdf(category.lower(), dest_pdf_text)
    if sims and sims[0].get("distance", None) == -1.0:
        logger.info(f"[v2] Exact match found - using cached result")
        result_json = sims[0]["json_data"]
    else:
        logger.info(f"[v2] Skipping RAG samples - extracting directly from repaired text")
        temp = time.perf_counter()
        required_keys = get_required_keys(category)
        if not required_keys:
            return JSONResponse(
                status_code=400,
                content={"error": f"Unknown category or no configured keys: {category}"}
            )

        field_list = "\n".join([f"- {k}" for k in required_keys])
        extract_system_prompt = """
You are an expert in health insurance plan data extraction. Your task is to extract specific fields from a Summary of Benefits and Coverage (SBC) document and return them as a structured JSON object.

Follow these rules strictly:
1. Only extract the fields provided in the user's field list. Do not add extra fields.
2. If a field value is not explicitly stated in the document, use "Not specified" as the value.
3. For numeric fields with dollar amounts, preserve the format exactly as shown (e.g., "$40 / visit", "$8,500").
4. For fields with multiple services or conditions, combine them into a single string with appropriate formatting.
5. For Out-of-Network values that are not covered, use "Not covered".
6. For deductibles that do not apply, use "Not Applicable".
7. Interpret the document carefully—some values may be implied from context, not explicitly labeled.
8. Return only valid JSON, no additional text or explanation.
""".strip()

        extract_user_prompt = f"""
Extract the following fields from the provided Summary of Benefits and Coverage document and return them as a JSON object:

Field list:
{field_list}

Here is the SBC document content:
{dest_pdf_text}
""".strip()

        raw = await llm.chat(extract_system_prompt, extract_user_prompt, max_new_tokens=4000)

        if isinstance(raw, dict):
            result_json = raw
        else:
            s = raw.strip() if isinstance(raw, str) else ""
            try:
                result_json = json.loads(s[s.find("{"): s.rfind("}") + 1])
            except Exception as ex:
                result_json = {
                    "error": f"Failed to parse JSON from LLM output: {ex}",
                    "raw": s[:400],
                }

        if isinstance(result_json, dict):
            result_json = replace_nulls(result_json)
            result_json = filter_to_required_keys(result_json, required_keys)

        logger.info(f"[v2] LLM extraction completed in {time.perf_counter() - temp:.2f}s")
        temp = time.perf_counter()

        # Post-process validation: Check for potentially missed out-of-network values
        validation_result = validate_out_of_network_extraction(result_json, dest_pdf_text, category)
        if not validation_result["valid"]:
            logger.warning(f"[v2] Validation warnings: {validation_result['warnings']}")

    logger.info(f"[v2] Total extraction_v2 process completed in {time.perf_counter() - start:.2f}s")

    return result_json


@app.post("/llm_test")
async def llm_test_endpoint(
    api_key: str = Depends(get_api_key),
    prompt: str = Body(..., media_type="text/plain"),
):
    """
    Quick prompt test endpoint for the configured LLM.

    The HTTP request body should be ONLY the prompt content (raw text).
    If the body accidentally comes as a JSON string (e.g. "\"hello\""), we try to decode it.
    """
    start = time.perf_counter()

    system_prompt = "You are a helpful assistant."
    raw_prompt = prompt.strip()

    # Fallback: if caller accidentally sends a JSON string in a text/plain body
    # (e.g. "\"hello\""), decode it once.
    if len(raw_prompt) >= 2 and raw_prompt[0] == '"' and raw_prompt[-1] == '"':
        try:
            maybe = json_lib.loads(raw_prompt)
            if isinstance(maybe, str):
                raw_prompt = maybe
        except Exception:
            pass

    raw = await llm.chat(system_prompt, raw_prompt, max_new_tokens=800)

    logger.info(f"/llm_test completed in {time.perf_counter() - start:.2f}s")
    return {"result": raw}

@app.post("/sample/add_one")
async def add_sample_endpoint(
    pdf_file: UploadFile = File(...),
    json_file: UploadFile = File(...),
    category: str = Form(...),
    api_key: str = Depends(get_api_key)
):
    start = time.perf_counter()
    temp = start

    pdf_bytes = await pdf_file.read()
    json_bytes = await json_file.read()
    json_data = json.loads(json_bytes.decode())

    print(f"Elapsed time for loading input file: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    # Initialize db by category
    db.init_sqlite(category)

    print(f"Elapsed time for db initialization: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    # Exact deduplication: check for identical PDF by hash
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    
    paths = db._get_category_paths(category)
    conn = sqlite3.connect(paths["sqlite"])
    c = conn.cursor()
    
    # Check if sample exists
    c.execute('SELECT id, pdf_path FROM samples WHERE pdf_hash=?', (pdf_hash,))
    row = c.fetchone()
   
    print(f"Elapsed time for connection to db: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    if row:
        sample_id, _ = row
        
        # Use helper function to update
        success = update_sample_in_db(category.lower(), sample_id, pdf_bytes, json_data, paths, conn)
        
        if success:
            conn.commit()
            conn.close()
            return {"status": "updated", "sample_id": sample_id}
        else:
            conn.close()
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to update sample {sample_id}"}
            )

    # If not duplicate, insert new
    sample_id = db.add_sample_to_db(category.lower(), pdf_bytes, json_data, pdf_hash)
    print(f"Elapsed time for adding sample to db: {time.perf_counter() - temp:.2f} seconds")
    temp = time.perf_counter()

    return {"status": "ok", "sample_id": sample_id}


@app.post("/sample/add_batch")
async def add_batch_endpoint(
    folder_path: str = Body(...),
    category: str = Body(...),
    api_key: str = Depends(get_api_key)
):
    # Normalize path: replace backslashes with forward slashes for cross-platform compatibility
    # Also handle escaped backslashes that might come from JSON
    folder_path = folder_path.replace('\\', os.sep).replace('/', os.sep)
    folder_path = os.path.normpath(folder_path)  # Normalize the path
    
    logger.info(f"Processing batch add for folder: {folder_path}, category: {category}")
    
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

    paths = db._get_category_paths(category)
    conn = sqlite3.connect(paths["sqlite"])
    c = conn.cursor()
    
    # Preload all existing PDF hashes with sample IDs for efficiency
    c.execute('SELECT pdf_hash, id FROM samples')
    existing_data = {row[0]: row[1] for row in c.fetchall()}

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

            # Read JSON
            with open(json_path, "r", encoding="utf-8") as jf:
                json_data = json.load(jf)

            # Check for duplicate - if exists, UPDATE instead of skip
            if pdf_hash in existing_data:
                sample_id = existing_data[pdf_hash]
                logger.info(f"Updating existing sample in batch: {sample_id}")
                
                # Use helper function to update
                success = update_sample_in_db(category.lower(), sample_id, pdf_bytes, json_data, paths, conn)
                
                if success:
                    conn.commit()
                    results.append({
                        "pdf_file": pdf_file,
                        "status": "updated",
                        "sample_id": sample_id
                    })
                else:
                    results.append({
                        "pdf_file": pdf_file,
                        "status": "error",
                        "reason": f"Failed to update sample {sample_id}"
                    })
            else:
                # Add new sample to DB
                sample_id = db.add_sample_to_db(category.lower(), pdf_bytes, json_data, pdf_hash)
                
                # Update our cache
                existing_data[pdf_hash] = sample_id
                
                results.append({
                    "pdf_file": pdf_file,
                    "status": "ok",
                    "sample_id": sample_id
                })

        except Exception as e:
            logger.error(f"Error processing {pdf_file}: {e}")
            results.append({
                "pdf_file": pdf_file,
                "status": "error",
                "reason": str(e)
            })
    
    conn.close()

    return {
        "processed": len(pdf_files),
        "successes": sum(r["status"] == "ok" for r in results),
        "updated": sum(r["status"] == "updated" for r in results),
        "failures": [r for r in results if r["status"] not in ["ok", "updated"]],
        "results": results
    }
