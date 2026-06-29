import os
import json
import uuid
import sqlite3
import numpy as np
import faiss
import time
import re

from threading import Lock
from .extract import pdf_to_text
from .embedder import get_embedding
from .category_key_registry import get_required_keys

# DB config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(os.path.dirname(BASE_DIR), 'db')  # Go up one level from app/
DB_DIR = os.path.abspath(DB_DIR)
os.makedirs(DB_DIR, exist_ok=True)

# Embedding dimension (must match your model)
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2

def _get_category_paths(category: str):
    """
    Return paths for FAISS index, metadata sqlite, and faiss-ids file
    based on category.
    """
    safe_cat = category.lower().replace(" ", "_")
    cat_dir = os.path.join(DB_DIR, safe_cat)
    os.makedirs(cat_dir, exist_ok=True)

    return {
        "cat_dir": cat_dir,
        "vector_db": os.path.join(cat_dir, "faiss.index"),
        "sqlite": os.path.join(cat_dir, "metadata.sqlite"),
        "faiss_ids": os.path.join(cat_dir, "faiss-ids.txt"),
    }

def init_sqlite(category: str = ""):
    if category == "":
        return
    paths = _get_category_paths(category)
    conn = sqlite3.connect(paths["sqlite"])
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS samples
        (id TEXT PRIMARY KEY, 
         category TEXT, 
         carrier TEXT, 
         plan TEXT, 
         json_data TEXT, 
         pdf_path TEXT,
         pdf_hash TEXT
        )
    ''')
    # Backward-compatible migration: store original raw PDF filename separately.
    c.execute("PRAGMA table_info(samples)")
    cols = [row[1] for row in c.fetchall()]
    if "raw_pdf_path" not in cols:
        c.execute("ALTER TABLE samples ADD COLUMN raw_pdf_path TEXT")
    conn.commit()
    conn.close()

def safe_filename(name: str) -> str:
    # Replace all illegal filename chars with _
    name = re.sub(r'[\/\\:*?"<>|]', "_", name)
    # Replace spaces with underscore (optional)
    name = re.sub(r'\s+', '_', name)
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)
    # Remove leading/trailing underscores, dots, or spaces
    name = name.strip(' ._')
    return name

def add_sample_to_db(category: str, pdf_bytes: bytes, json_data: dict, pdf_hash: str) -> str:
    # Add debugging
    paths = _get_category_paths(category)
    print(f"DEBUG: Category directory: {paths['cat_dir']}")
    print(f"DEBUG: Directory exists: {os.path.exists(paths['cat_dir'])}")
    print(f"DEBUG: Directory writable: {os.access(paths['cat_dir'], os.W_OK)}")
    
    # Extract metadata
    carrier = json_data.get('Carrier Name', '')
    plan = json_data.get('Plan Name', '')

    paths = _get_category_paths(category)
    init_sqlite(category)

    sample_id = carrier + "_" + plan + "_" + str(uuid.uuid4())[:10]
    sample_id = safe_filename(sample_id)

    # Parse PDF to text ONCE
    text = pdf_to_text(pdf_bytes)
    
    print(f"\n=== ADD SAMPLE: Text Extraction ===")
    print(f"Sample ID: {sample_id}")
    print(f"Text length: {len(text)} characters")
    print(f"Text preview (first 200 chars): {text[:200]}")
    print(f"Text preview (last 200 chars): {text[-200:]}")
    print(f"===================================\n")
    
    # Save parsed text used by current embedding/search flow
    txt_filename = f"{sample_id}.txt"
    txt_path = os.path.join(paths["cat_dir"], txt_filename)
    try:
        with open(txt_path, "w", encoding="utf-8") as tf:
            tf.write(text)
        print(f"DEBUG: Successfully wrote file: {txt_path}")
    except Exception as e:
        print(f"ERROR: Failed to write file {txt_path}: {e}")
        raise

    # Save original raw PDF as well
    raw_pdf_filename = f"{sample_id}.pdf"
    raw_pdf_path = os.path.join(paths["cat_dir"], raw_pdf_filename)
    try:
        with open(raw_pdf_path, "wb") as pf:
            pf.write(pdf_bytes)
        print(f"DEBUG: Successfully wrote raw PDF file: {raw_pdf_path}")
    except Exception as e:
        print(f"ERROR: Failed to write raw PDF file {raw_pdf_path}: {e}")
        raise

    # Save metadata in SQLite
    conn = sqlite3.connect(paths["sqlite"])
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO samples (id, category, carrier, plan, json_data, pdf_path, pdf_hash, raw_pdf_path)
        VALUES (?,?,?,?,?,?,?,?)
        ''',
        (sample_id, category, carrier, plan, json.dumps(json_data), txt_filename, pdf_hash, raw_pdf_filename)
    )
 
    conn.commit()
    conn.close()

    # Embed PDF text, add to FAISS
    emb = np.array(get_embedding(text), dtype=np.float32)[np.newaxis, :]

    if not os.path.exists(paths["vector_db"]):
        index = faiss.IndexFlatL2(EMBEDDING_DIM)
        faiss.write_index(index, paths["vector_db"])
    index = faiss.read_index(paths["vector_db"])
    index.add(emb)
    faiss.write_index(index, paths["vector_db"])

    # Save mapping index to sample_id
    with open(paths["faiss_ids"], "a", encoding="utf-8") as f:
        f.write(f"{sample_id}\n")

    return sample_id

_sqlite_conns = {}
_sqlite_lock = Lock()  # avoid concurrency issues

def get_faiss_index(category):
    paths = _get_category_paths(category)
    return faiss.read_index(paths["vector_db"])

def get_faiss_ids(category):
    paths = _get_category_paths(category)
    with open(paths["faiss_ids"], encoding="utf-8", errors="ignore") as f:
        return [l.strip() for l in f]

def get_sqlite_conn(category):
    """Keep one SQLite connection open per category."""
    if category not in _sqlite_conns:
        paths = _get_category_paths(category)
        conn = sqlite3.connect(paths["sqlite"], check_same_thread=False)
        conn.row_factory = sqlite3.Row
        with _sqlite_lock:
            _sqlite_conns[category] = conn
    return _sqlite_conns[category]

def _score_out_of_network_coverage(json_data: dict, category: str) -> float:
    """
    Score how well a JSON sample covers out-of-network values.
    Returns a score from 0.0 to 1.0, where 1.0 means excellent coverage.
    
    For categories without out-of-network fields, returns 1.0 (neutral).
    """
    required_keys = get_required_keys(category)
    
    # Find all out-of-network fields for this category
    out_of_network_fields = [k for k in required_keys if k.startswith("Out-of-Network")]
    
    # If no out-of-network fields, return neutral score
    if not out_of_network_fields:
        return 1.0
    
    # Count how many out-of-network fields have valid (non-empty) values
    valid_count = 0
    total_count = len(out_of_network_fields)
    
    for field in out_of_network_fields:
        value = json_data.get(field, "")
        # Consider a value valid if it's not empty and not "not covered" (case insensitive)
        if value and str(value).strip().lower() not in ["", "not covered", "n/a", "na", "none"]:
            valid_count += 1
    
    # Return score as ratio of valid fields
    score = valid_count / total_count if total_count > 0 else 0.0
    return score

def search_similar_pdf(category: str, text: str):
    top_k=10  # Search more candidates to have better selection pool
    paths = _get_category_paths(category)
    if not os.path.exists(paths["vector_db"]):
        return []

    index = get_faiss_index(category)
    id_list = get_faiss_ids(category)
    
    # Validate index integrity
    if index.ntotal != len(id_list):
        print(f"⚠️  WARNING: FAISS index corruption detected!")
        print(f"   FAISS index has {index.ntotal} embeddings")
        print(f"   But faiss-ids.txt has {len(id_list)} entries")
        print(f"   This happens when updates corrupted the index.")
        print(f"   Solution: Delete db/{category}/ and re-add all samples\n")

    # Use a fresh connection for each request (for reads)
    conn = sqlite3.connect(paths["sqlite"])
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    print(f"\n=== SEARCH: Text Extraction ===")
    print(f"Text length: {len(text)} characters")
    print(f"Text preview (first 200 chars): {text[:200]}")
    print(f"Text preview (last 200 chars): {text[-200:]}")
    print(f"================================\n")
    
    emb = np.array(get_embedding(text), dtype=np.float32)[np.newaxis, :]
    D, I = index.search(emb, top_k)
    
    print(f"Top {top_k} similar samples:")
    
    found = []
    foundids = []
    for idx, pos in enumerate(I[0]):
        if pos >= len(id_list):
            continue
        distance = float(D[0][idx])
        # Skip samples with exact zero distance – these usually come from
        # degenerate or duplicate embeddings and do not help as useful RAG
        # references for new documents.
        if distance == 0.0:
            continue
        sample_id = id_list[pos]
        c.execute('SELECT json_data, pdf_path FROM samples WHERE id=?', (sample_id,))
        row = c.fetchone()
        if row:
            txt_path = os.path.join(paths["cat_dir"], row["pdf_path"])
            json_data = json.loads(row["json_data"])
            # Score the out-of-network coverage
            oon_score = _score_out_of_network_coverage(json_data, category)
            
            found.append({
                "id": sample_id,
                "json_data": json_data,
                "txt_path": txt_path,
                "distance": distance,
                "out_of_network_score": oon_score,
            })
            
            print(f"  {idx+1}. distance={distance:.6f} | {sample_id}")

            foundids.append(sample_id)
    
    print()
    conn.close()

    # Compare actual text for exact match (95% of shorter text)
    print(f"\n=== Checking for exact text matches ===")
    
    for sample in found:
        try:
            with open(sample["txt_path"], "r", encoding="utf-8") as tf:
                sample_text = tf.read()
            
            # Compare 95% of the shorter text
            sample_stripped = sample_text.strip()
            text_stripped = text.strip()
            
            print(f"\nComparing: {sample['id']}")
            print(f"  Sample text length: {len(sample_stripped)}")
            print(f"  Query text length: {len(text_stripped)}")
            print(f"  Distance from FAISS: {sample['distance']:.6f}")
            
            # Find the shorter length and calculate 95% of it
            shorter_length = min(len(sample_stripped), len(text_stripped))
            compare_length = int(shorter_length * 0.95)
            
            # Compare first 95% of shorter text
            sample_compare = sample_stripped[:compare_length]
            text_compare = text_stripped[:compare_length]
            
            if sample_compare == text_compare:
                print(f"  ✓ EXACT MATCH found! (95% comparison)")
                print(f"  Compared first {compare_length} characters (95% of {shorter_length})")
                # Exact match found, return only this sample
                sample["distance"] = -1.0
                return [sample]
            else:
                # Find first difference
                for i in range(min(len(sample_compare), len(text_compare))):
                    if sample_compare[i] != text_compare[i]:
                        print(f"  ✗ First difference at position {i}")
                        print(f"    Context: ...{sample_compare[max(0,i-30):i+30]}...")
                        print(f"    vs:      ...{text_compare[max(0,i-30):i+30]}...")
                        break
                    
        except Exception as e:
            print(f"  Error comparing sample text: {e}")
            continue
    
    print(f"=== No exact match found ===\n")

    # No exact match - select best sample based on combination of similarity and out-of-network coverage
    if not found:
        return []
    
    # Score each sample: lower distance (better similarity) + higher out-of-network score (better coverage)
    # Normalize distance to 0-1 range (assuming max reasonable distance is around 50, but we'll use relative)
    if len(found) > 1:
        max_distance = max(s["distance"] for s in found)
        min_distance = min(s["distance"] for s in found)
        distance_range = max_distance - min_distance if max_distance > min_distance else 1.0
        
        for sample in found:
            # Normalize distance: lower is better, so we invert it
            normalized_distance_score = 1.0 - ((sample["distance"] - min_distance) / distance_range) if distance_range > 0 else 1.0
            
            # Combined score: 60% weight on similarity, 40% weight on out-of-network coverage
            # This ensures we prefer similar documents, but boost those with better OON coverage
            # Only apply 60%/40% ratio if distance > 0.05, otherwise use only distance-based score
            if sample["distance"] > 0.07:
                sample["combined_score"] = 0.6 * normalized_distance_score + 0.4 * sample["out_of_network_score"]
            else:
                sample["combined_score"] = normalized_distance_score
 
        # Sort by combined score (descending) and return top one
        found.sort(key=lambda x: x["combined_score"], reverse=True)
        # Log foundids after rescoring (ordered by combined score)
        rescored_foundids = [s["id"] for s in found]
        print(f"Selected sample with distance={found[0]['distance']:.4f}, oon_score={found[0]['out_of_network_score']:.2f}, combined_score={found[0]['combined_score']:.2f}")
        print(f"foundids after rescoring (ordered by combined score): {rescored_foundids}")
    else:
        # Single sample case - still log it
        print(f"Selected sample (single candidate) with distance={found[0]['distance']:.4f}, oon_score={found[0]['out_of_network_score']:.2f}")
        print(f"foundids after rescoring: {[found[0]['id']]}")
    
    return [found[0]]

def get_sample_json_by_id(category: str, sample_id: str) -> dict:
    paths = _get_category_paths(category)
    conn = sqlite3.connect(paths["sqlite"])
    c = conn.cursor()
    c.execute('SELECT json_data FROM samples WHERE id=?', (sample_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return {}
