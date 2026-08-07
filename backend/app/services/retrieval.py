from __future__ import annotations

import math

from app.services.ingestion import ChunkDraft, _tokenize, _vectorize


def _dot(a: dict[str, int], b: dict[str, int]) -> float:
    keys = a.keys() & b.keys()
    return float(sum(a[key] * b[key] for key in keys))


def _norm(vector: dict[str, int]) -> float:
    return math.sqrt(sum(value * value for value in vector.values()))


def cosine_similarity(a: dict[str, int], b: dict[str, int]) -> float:
    denominator = _norm(a) * _norm(b)
    if denominator == 0:
        return 0.0
    return _dot(a, b) / denominator


def rank_chunks(question: str, chunks: list[ChunkDraft], top_k: int = 5) -> list[tuple[ChunkDraft, float]]:
    query_vector = _vectorize(question)
    scored = []
    for chunk in chunks:
        score = cosine_similarity(query_vector, chunk.vector)
        if score > 0:
            scored.append((chunk, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]
