"""Ingestion, semantic search and RAG question answering."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Business, Document, DocumentChunk
from . import documents as docs
from .embeddings import get_embedder
from .llm import invoke_text
from .vectorstore import VectorStore

log = logging.getLogger(__name__)
MIN_SCORE = 0.08


def _ensure_index(db: Session, business_id: int):
    """Rebuild the FAISS index from stored chunks if the embedding provider changed."""
    emb = get_embedder()
    store = VectorStore(business_id)
    meta = store.meta()
    if meta.get("provider") == emb.name:
        return store, emb
    chunks = db.execute(select(DocumentChunk).where(DocumentChunk.business_id == business_id)).scalars().all()
    store.reset(emb.name, emb.dim)
    for i in range(0, len(chunks), 64):
        batch = chunks[i:i + 64]
        store.add([c.id for c in batch], emb.embed([c.text for c in batch]), emb.name)
    return store, emb


def ingest_text(db: Session, business_id: int, filename: str, file_type: str, size: int, text: str) -> Document:
    doc = Document(business_id=business_id, filename=filename, file_type=file_type, size_bytes=size,
                   status="processing")
    db.add(doc)
    db.flush()
    try:
        pieces = docs.chunk_text(text, settings.chunk_size, settings.chunk_overlap)
        if not pieces:
            raise docs.DocumentError("No readable text was found in this document (scanned PDFs need OCR).")
        rows = [DocumentChunk(business_id=business_id, document_id=doc.id, chunk_index=i, text=t)
                for i, t in enumerate(pieces)]
        db.add_all(rows)
        db.flush()
        store, emb = _ensure_index(db, business_id)
        store.add([r.id for r in rows], emb.embed(pieces), emb.name)
        doc.status, doc.chunk_count, doc.char_count = "ready", len(rows), len(text)
    except Exception as exc:
        log.warning("Document ingestion failed: %s", exc)
        db.rollback()
        doc = Document(business_id=business_id, filename=filename, file_type=file_type, size_bytes=size,
                       status="failed", error=str(exc)[:500])
        db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def delete_document(db: Session, doc: Document):
    ids = [c.id for c in doc.chunks]
    VectorStore(doc.business_id).remove(ids)
    db.delete(doc)
    db.commit()


def search(db: Session, business_id: int, query: str, k: int = 5) -> list[dict]:
    if not query.strip():
        return []
    store, emb = _ensure_index(db, business_id)
    hits = store.search(emb.embed([query])[0], k)
    if not hits:
        return []
    scores = dict(hits)
    rows = db.execute(select(DocumentChunk, Document.filename).join(Document, Document.id == DocumentChunk.document_id)
                      .where(DocumentChunk.business_id == business_id, DocumentChunk.id.in_(scores.keys()))).all()
    results = [{"chunk_id": c.id, "document_id": c.document_id, "filename": fn, "text": c.text,
                "score": round(scores[c.id], 4)} for c, fn in rows if scores[c.id] >= MIN_SCORE]
    return sorted(results, key=lambda r: -r["score"])


def format_context(results: list[dict]) -> str:
    return "\n\n".join(f"[Source: {r['filename']}]\n{r['text']}" for r in results)


def answer_question(db: Session, business: Business, question: str) -> dict:
    results = search(db, business.id, question, k=5)
    if not results:
        return {"answer": "I couldn't find anything about that in your uploaded documents.",
                "sources": [], "grounded": False}
    system = (f"You answer questions for {business.name} using ONLY the context provided. "
              "If the context does not contain the answer, say you don't have that information. "
              "Never invent facts, prices or policies.")
    answer = invoke_text(system, f"Context:\n{format_context(results)}\n\nQuestion: {question}")
    return {"answer": answer, "grounded": True,
            "sources": [{"filename": r["filename"], "score": r["score"], "excerpt": r["text"][:240]} for r in results]}
