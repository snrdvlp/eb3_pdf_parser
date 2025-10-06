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

# DB config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, '..', 'db')
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
    # Extract metadata
    carrier = json_data.get('Carrier Name', '')
    plan = json_data.get('Plan Name', '')

    paths = _get_category_paths(category)
    init_sqlite(category)

    sample_id = carrier + "_" + plan + "_" + str(uuid.uuid4())[:10]
    sample_id = safe_filename(sample_id)

    # Parse PDF to text ONCE
    text = pdf_to_text(pdf_bytes)
    # Save parsed text instead of PDF
    txt_filename = f"{sample_id}.txt"
    txt_path = os.path.join(paths["cat_dir"], txt_filename)
    with open(txt_path, "w", encoding="utf-8") as tf:
        tf.write(text)
    
    # Save metadata in SQLite
    conn = sqlite3.connect(paths["sqlite"])
    c = conn.cursor()
    c.execute('INSERT INTO samples VALUES (?,?,?,?,?,?,?)',
              (sample_id, category, carrier, plan, json.dumps(json_data), txt_filename, pdf_hash))
 
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

_faiss_indexes = {}
_faiss_ids = {}
_sqlite_conns = {}
_sqlite_lock = Lock()  # avoid concurrency issues

def get_faiss_index(category):
    if category not in _faiss_indexes:
        paths = _get_category_paths(category)
        _faiss_indexes[category] = faiss.read_index(paths["vector_db"])
    return _faiss_indexes[category]

def get_faiss_ids(category):
    if category not in _faiss_ids:
        paths = _get_category_paths(category)
        with open(paths["faiss_ids"], encoding="utf-8", errors="ignore") as f:
            _faiss_ids[category] = [l.strip() for l in f]
    return _faiss_ids[category]

def get_sqlite_conn(category):
    """Keep one SQLite connection open per category."""
    if category not in _sqlite_conns:
        paths = _get_category_paths(category)
        conn = sqlite3.connect(paths["sqlite"], check_same_thread=False)
        conn.row_factory = sqlite3.Row
        with _sqlite_lock:
            _sqlite_conns[category] = conn
    return _sqlite_conns[category]

def search_similar_pdf(category: str, text: str, top_k=1):
    start = time.perf_counter()
    temp = start

    paths = _get_category_paths(category)
    if not os.path.exists(paths["vector_db"]):
        return []

    index = get_faiss_index(category)
    id_list = get_faiss_ids(category)

    # Use a fresh connection for each request (for reads)
    conn = sqlite3.connect(paths["sqlite"])
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    emb = np.array(get_embedding(text), dtype=np.float32)[np.newaxis, :]
    D, I = index.search(emb, top_k)
    found = []
    for pos in I[0]:
        if pos >= len(id_list):
            continue
        sample_id = id_list[pos]
        c.execute('SELECT json_data, pdf_path FROM samples WHERE id=?', (sample_id,))
        row = c.fetchone()
        if row:
            found.append({
                "id": sample_id,
                "json_data": json.loads(row["json_data"]),
                "txt_path": os.path.join(paths["cat_dir"], row["pdf_path"]),
            })
    conn.close()
    return found

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
