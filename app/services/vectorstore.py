"""Per-business FAISS index persisted on disk (IndexIDMap2 over inner-product, ids = chunk ids)."""
import json
import os
import threading
from pathlib import Path

import faiss
import numpy as np

from ..config import settings

_locks: dict[int, threading.Lock] = {}
_guard = threading.Lock()


def _lock_for(bid: int) -> threading.Lock:
    with _guard:
        return _locks.setdefault(bid, threading.Lock())


def _paths(bid: int):
    d = Path(settings.vector_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"business_{bid}.faiss", d / f"business_{bid}.json"


class VectorStore:
    def __init__(self, business_id: int):
        self.bid = business_id
        self.index_path, self.meta_path = _paths(business_id)

    def meta(self) -> dict:
        if self.meta_path.exists():
            try:
                return json.loads(self.meta_path.read_text())
            except ValueError:
                return {}
        return {}

    def _load(self, dim: int):
        if self.index_path.exists():
            idx = faiss.read_index(str(self.index_path))
            if idx.d == dim:
                return idx
        return faiss.IndexIDMap2(faiss.IndexFlatIP(dim))

    def _save(self, idx, provider: str):
        faiss.write_index(idx, str(self.index_path))
        self.meta_path.write_text(json.dumps({"provider": provider, "count": idx.ntotal}))

    def reset(self, provider: str, dim: int):
        with _lock_for(self.bid):
            self._save(faiss.IndexIDMap2(faiss.IndexFlatIP(dim)), provider)

    def add(self, ids: list[int], vectors: np.ndarray, provider: str):
        if not ids:
            return
        with _lock_for(self.bid):
            idx = self._load(vectors.shape[1])
            idx.remove_ids(np.array(ids, dtype="int64"))
            idx.add_with_ids(vectors.astype("float32"), np.array(ids, dtype="int64"))
            self._save(idx, provider)

    def remove(self, ids: list[int]):
        if not ids or not self.index_path.exists():
            return
        with _lock_for(self.bid):
            idx = faiss.read_index(str(self.index_path))
            idx.remove_ids(np.array(ids, dtype="int64"))
            self._save(idx, self.meta().get("provider", ""))

    def search(self, vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        if not self.index_path.exists():
            return []
        with _lock_for(self.bid):
            idx = faiss.read_index(str(self.index_path))
        if idx.ntotal == 0:
            return []
        scores, ids = idx.search(vector.astype("float32").reshape(1, -1), min(k, idx.ntotal))
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

    def delete_files(self):
        for p in (self.index_path, self.meta_path):
            if os.path.exists(p):
                os.remove(p)
