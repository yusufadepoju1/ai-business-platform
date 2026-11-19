"""Upload validation, text extraction and chunking for PDF / TXT / DOCX."""
import io
import re
import zipfile

ALLOWED = {"pdf", "txt", "docx"}


class DocumentError(ValueError):
    pass


def safe_filename(name: str) -> str:
    name = (name or "document").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.\- ]", "_", name).strip() or "document"
    return name[:200]


def file_extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def validate_upload(filename: str, data: bytes, max_bytes: int) -> str:
    ext = file_extension(filename)
    if ext not in ALLOWED:
        raise DocumentError("Unsupported file type. Upload a PDF, TXT or DOCX file.")
    if not data:
        raise DocumentError("The file is empty.")
    if len(data) > max_bytes:
        raise DocumentError(f"File is too large. The limit is {max_bytes // (1024 * 1024)} MB.")
    if ext == "pdf" and not data.lstrip()[:5] == b"%PDF-":
        raise DocumentError("This file is not a valid PDF.")
    if ext == "docx" and not (data[:2] == b"PK" and zipfile.is_zipfile(io.BytesIO(data))):
        raise DocumentError("This file is not a valid DOCX document.")
    if ext == "txt" and b"\x00" in data[:4096]:
        raise DocumentError("This file does not look like plain text.")
    return ext


def extract_text(ext: str, data: bytes) -> str:
    try:
        if ext == "txt":
            for enc in ("utf-8", "utf-16", "latin-1"):
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
        if ext == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise DocumentError("Encrypted PDFs are not supported.")
            return "\n\n".join((p.extract_text() or "") for p in reader.pages)
        if ext == "docx":
            import docx
            d = docx.Document(io.BytesIO(data))
            parts = [p.text for p in d.paragraphs]
            for table in d.tables:
                for row in table.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            return "\n".join(parts)
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"Could not read the document: {exc}") from exc
    raise DocumentError("Unsupported file type.")


def chunk_text(text: str, size: int = 800, overlap: int = 120) -> list[str]:
    """Paragraph-aware splitter with character overlap."""
    text = re.sub(r"[ \t]+", " ", text.replace("\r", ""))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    pieces: list[str] = []
    for p in paras:
        if len(p) <= size:
            pieces.append(p)
        else:  # split long paragraphs on sentence boundaries, then hard-wrap
            sentences = re.split(r"(?<=[.!?])\s+", p)
            cur = ""
            for s in sentences:
                while len(s) > size:
                    if cur:
                        pieces.append(cur)
                        cur = ""
                    pieces.append(s[:size])
                    s = s[size - overlap:]
                if len(cur) + len(s) + 1 <= size:
                    cur = f"{cur} {s}".strip()
                else:
                    pieces.append(cur)
                    cur = s
            if cur:
                pieces.append(cur)
    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        if not cur:
            cur = piece
        elif len(cur) + len(piece) + 2 <= size:
            cur = f"{cur}\n\n{piece}"
        else:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = f"{tail} {piece}".strip() if tail and len(tail) + len(piece) + 1 <= size else piece
    if cur:
        chunks.append(cur)
    return chunks
