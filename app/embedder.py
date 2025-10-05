from sentence_transformers import SentenceTransformer

# Load model (downloads automatically if not present)
SBERT_MODEL = "all-MiniLM-L6-v2"
sbert = SentenceTransformer(SBERT_MODEL)

def get_embedding(text: str) -> list:
    embedding = sbert.encode(text)  # returns a numpy array
    return embedding.tolist()
