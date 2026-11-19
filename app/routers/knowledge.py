from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import admin_user, current_business, current_user, get_owned
from ..models import Business, Document, User
from ..ratelimit import rate_limit
from ..services import documents as docs
from ..services import rag
from ..services.llm import LLMUnavailable

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def doc_out(d: Document) -> dict:
    return {"id": d.id, "filename": d.filename, "file_type": d.file_type, "size_bytes": d.size_bytes, "status": d.status,
            "error": d.error, "chunk_count": d.chunk_count, "char_count": d.char_count, "created_at": d.created_at}


@router.get("/documents")
def list_documents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Document).where(Document.business_id == user.business_id).order_by(Document.id.desc())).scalars()
    return [doc_out(d) for d in rows]


@router.post("/documents", status_code=201, dependencies=[Depends(rate_limit("upload", 30, 60))])
async def upload_document(file: UploadFile = File(...), user: User = Depends(admin_user), db: Session = Depends(get_db)):
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    name = docs.safe_filename(file.filename or "")
    try:
        ext = docs.validate_upload(name, data, limit)
        text = docs.extract_text(ext, data)
    except docs.DocumentError as exc:
        raise HTTPException(422, str(exc))
    doc = rag.ingest_text(db, user.business_id, name, ext, len(data), text)
    if doc.status == "failed":
        raise HTTPException(422, doc.error)
    return doc_out(doc)


@router.get("/documents/{doc_id}")
def document_detail(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = get_owned(db, Document, doc_id, user.business_id)
    out = doc_out(d)
    out["preview"] = [c.text[:300] for c in d.chunks[:5]]
    return out


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    rag.delete_document(db, get_owned(db, Document, doc_id, user.business_id))
    return {"ok": True}


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=5, ge=1, le=10)


@router.post("/search")
def semantic_search(body: SearchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return rag.search(db, user.business_id, body.query, body.k)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@router.post("/ask", dependencies=[Depends(rate_limit("ask", 30, 60))])
def ask(body: AskIn, biz: Business = Depends(current_business), db: Session = Depends(get_db)):
    try:
        return rag.answer_question(db, biz, body.question)
    except LLMUnavailable as exc:
        raise HTTPException(503, str(exc))
