from openai import OpenAI
import numpy as np
import os
from dotenv import load_dotenv

load_dotenv()

# For OpenAI embeddings
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
                
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"

def get_embedding(text: str) -> list:
    resp = client.embeddings.create(
        model=OPENAI_EMBEDDING_MODEL,
        input=text[:8192]
    )
    return resp.data[0].embedding