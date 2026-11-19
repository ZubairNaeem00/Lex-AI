"""Qwen3-Embedding wrapper for the raw FAISS legal indexes.

Qwen3-Embedding is asymmetric: documents are encoded WITHOUT an instruction,
queries WITH one. The law and similar-case indexes were both built with
Qwen/Qwen3-Embedding-0.6B (1024-dim, unit-length vectors), so a single shared
model instance serves both and only the query prompt differs per index.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from langchain_core.embeddings import Embeddings

_model_cache: Dict[Any, Any] = {}
_model_lock = threading.Lock()


def get_qwen_model(
    model_name: str,
    device: str = "cpu",
    max_seq_length: int = 2048,
):
    """Load (once) and share a SentenceTransformer across retrievers."""
    key = (model_name, device, int(max_seq_length))
    cached = _model_cache.get(key)
    if cached is not None:
        return cached
    with _model_lock:
        cached = _model_cache.get(key)
        if cached is not None:
            return cached
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name, device=device)
        model.max_seq_length = int(max_seq_length)
        _model_cache[key] = model
        return model


class Qwen3Embeddings(Embeddings):
    """LangChain Embeddings interface over Qwen3-Embedding with a query prompt."""

    def __init__(
        self,
        model_name: str,
        query_prompt: str = "",
        device: str = "cpu",
        max_seq_length: int = 2048,
        batch_size: int = 16,
    ) -> None:
        self.model_name = model_name
        self.query_prompt = query_prompt or ""
        self.device = device
        self.max_seq_length = int(max_seq_length)
        self.batch_size = int(batch_size)
        self._model = get_qwen_model(model_name, device=device, max_seq_length=max_seq_length)

    def _encode(self, texts: List[str], with_prompt: bool) -> List[List[float]]:
        if not texts:
            return []
        payload = [self.query_prompt + t for t in texts] if with_prompt else list(texts)
        vectors = self._model.encode(
            payload,
            normalize_embeddings=True,
            convert_to_numpy=True,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._encode(texts, with_prompt=False)

    def embed_query(self, text: str) -> List[float]:
        return self._encode([text], with_prompt=True)[0]
