"""Embedding providers.

* sentence-transformers (default when installed and the model can be loaded)
* hashing: dependency-free lexical fallback (signed hashing of unigrams+bigrams, 384 dims).
  It is NOT a neural model; retrieval quality is keyword-oriented. The provider name is stored
  with each vector index so an index is rebuilt automatically when the provider changes.
"""
import hashlib
import logging
import re
import threading

import numpy as np

from ..config import settings

log = logging.getLogger(__name__)
DIM = 384
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "on", "with", "do", "you",
         "i", "it", "we", "my", "your", "what", "how", "can", "does", "at", "be", "this", "that"}


class HashingEmbedder:
    name = "hashing-384"
    dim = DIM

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), DIM), dtype="float32")
        for i, text in enumerate(texts):
            toks = [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]
            feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
            for f in feats:
                h = int.from_bytes(hashlib.md5(f.encode()).digest()[:8], "little")
                out[i, h % DIM] += 1.0 if (h >> 63) & 1 else -1.0
            out[i] = np.sign(out[i]) * np.log1p(np.abs(out[i]))
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


class SentenceTransformerEmbedder:
    dim = DIM

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # heavy import, lazy
        self._model = SentenceTransformer(model_name)
        self.name = f"st:{model_name}"
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> np.ndarray:
        v = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(v, dtype="float32")


_lock = threading.Lock()
_embedder = None


def get_embedder():
    global _embedder
    with _lock:
        if _embedder is not None:
            return _embedder
        provider = settings.embedding_provider.lower()
        if provider in ("auto", "sentence-transformers"):
            try:
                _embedder = SentenceTransformerEmbedder(settings.embedding_model)
                log.info("Embeddings: %s", _embedder.name)
                return _embedder
            except Exception as exc:  # not installed / model download blocked
                if provider == "sentence-transformers":
                    raise
                log.warning("sentence-transformers unavailable (%s); using hashing fallback embeddings.", exc)
        _embedder = HashingEmbedder()
        return _embedder


def reset_embedder():
    global _embedder
    _embedder = None
