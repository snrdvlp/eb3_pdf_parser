import os
import json
import uuid
import sqlite3
import numpy as np
import faiss

from .extract import pdf_to_text
from .embedder import get_embedding

# DB config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, '..', 'db')
DB_DIR = os.path.abspath(DB_DIR)

VECTOR_DB_FILE = os.path.join(DB_DIR, "faiss.index")
SQLITE_METADATA = os.path.join(DB_DIR, "metadata.sqlite")

os.makedirs(DB_DIR, exist_ok=True)

EMBEDDING_DIM = 1536  # OpenAI 'text-embedding-3-small'

def init_sqlite():
    conn = sqlite3.connect(SQLITE_METADATA)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS samples
        (id TEXT PRIMARY KEY, 
         category TEXT, 
         carrier TEXT, 
         plan TEXT, 
         json_data TEXT, 
         pdf_path TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_sample_to_db(category: str, pdf_bytes: bytes, json_data: dict) -> str:
    sample_id = str(uuid.uuid4())

    # Save PDF
    pdf_path = os.path.join(DB_DIR, f"{sample_id}.pdf")
    with open(pdf_path, "wb") as pf:
        pf.write(pdf_bytes)

    # Extract fields if available
    carrier = json_data.get('Carrier Name', '')
    plan = json_data.get('Plan Name', '')

    # Save metadata in SQLite
    conn = sqlite3.connect(SQLITE_METADATA)
    c = conn.cursor()
    c.execute('INSERT INTO samples VALUES (?,?,?,?,?,?)',
              (sample_id, category, carrier, plan, json.dumps(json_data), pdf_path))
    conn.commit()
    conn.close()

    # Embed PDF text, add to FAISS
    text = pdf_to_text(pdf_bytes)[:2000]  # truncate
    emb = np.array(get_embedding(text), dtype=np.float32)[np.newaxis, :]

    if not os.path.exists(VECTOR_DB_FILE):
        index = faiss.IndexFlatL2(EMBEDDING_DIM)
        faiss.write_index(index, VECTOR_DB_FILE)
    index = faiss.read_index(VECTOR_DB_FILE)
    index.add(emb)
    faiss.write_index(index, VECTOR_DB_FILE)

    # Save mapping index to sample_id
    with open(os.path.join(DB_DIR, "faiss-ids.txt"), "a") as f:
        f.write(f"{sample_id}\n")
    return sample_id

def search_similar_pdf(category: str, pdf_bytes: bytes, top_k=3):
    if not os.path.exists(VECTOR_DB_FILE):
        return []
    index = faiss.read_index(VECTOR_DB_FILE)
    text = pdf_to_text(pdf_bytes)[:2000]
    emb = np.array(get_embedding(text), dtype=np.float32)[np.newaxis, :]
    D, I = index.search(emb, top_k)

    # Load faiss-ids
    with open(os.path.join(DB_DIR, "faiss-ids.txt")) as f:
        id_list = [l.strip() for l in f.readlines()]
    found = []
    conn = sqlite3.connect(SQLITE_METADATA)
    c = conn.cursor()
    for pos in I[0]:
        if pos >= len(id_list):
            continue
        sample_id = id_list[pos]
        c.execute('SELECT json_data, pdf_path FROM samples WHERE id=?', (sample_id,))
        row = c.fetchone()
        if row:
            found.append({
                "id": sample_id,
                "json_data": json.loads(row[0]),
                "pdf_path": row[1]
            })
    conn.close()
    return found

def get_sample_json_by_id(sample_id: str) -> dict:
    conn = sqlite3.connect(SQLITE_METADATA)
    c = conn.cursor()
    c.execute('SELECT json_data FROM samples WHERE id=?', (sample_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return {}