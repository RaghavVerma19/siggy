import os
import hashlib
import math
import re
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

load_dotenv()

client = InferenceClient(token=os.getenv("HF_TOKEN"))

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMS = 384


def get_embedding(text: str) -> list[float]:
    try:
        response = client.feature_extraction(
            text=text,
            model=EMBEDDING_MODEL,
        )
        return response.tolist()
    except Exception:
        return _local_embedding(text)


def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    results = []
    for text in texts:
        results.append(get_embedding(text))
    return results


def _local_embedding(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMS
    tokens = re.findall(r"[a-z0-9_:-]+", (text or "").lower())
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + (len(token) / 32.0)
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
