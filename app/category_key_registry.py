import json
import os

# Load once and keep in memory
with open(os.path.join(os.path.dirname(__file__), 'category_keys.json')) as f:
    CATEGORY_KEYS = json.load(f)

def get_required_keys(category: str):
    # Fallback to [] for unknown category
    return CATEGORY_KEYS.get(category.lower(), [])