import io

import docx

from tests.conftest import KB


def make_docx(text: str) -> bytes:
    d = docx.Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_upload_txt_docx_pdf_and_search(client, tenant):
    h = tenant["h"]
    for name, data in [("kb.txt", KB), ("shipping.docx", make_docx("Shipping takes 3 to 5 business days within the country.")),
                       ("warranty.pdf", make_pdf("Warranty covers manufacturing defects for twelve months."))]:
        r = client.post("/api/knowledge/documents", headers=h, files={"file": (name, data, "application/octet-stream")})
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "ready" and r.json()["chunk_count"] >= 1
    docs = client.get("/api/knowledge/documents", headers=h).json()
    assert len(docs) == 3
    top = client.post("/api/knowledge/search", headers=h, json={"query": "how long does shipping take"}).json()
    assert top and top[0]["filename"] == "shipping.docx"
    top = client.post("/api/knowledge/search", headers=h, json={"query": "warranty defects"}).json()
    assert top[0]["filename"] == "warranty.pdf"


def test_upload_validation(client, tenant):
    h = tenant["h"]
    bad = [("evil.exe", b"MZ..."), ("fake.pdf", b"not a pdf at all"), ("fake.docx", b"not a zip"),
           ("empty.txt", b""), ("bin.txt", b"abc\x00\x01\x02")]
    for name, data in bad:
        assert client.post("/api/knowledge/documents", headers=h, files={"file": (name, data)}).status_code == 422, name
    big = b"a" * (10 * 1024 * 1024 + 10)
    assert client.post("/api/knowledge/documents", headers=h, files={"file": ("big.txt", big)}).status_code == 422
    # path traversal in filename is neutralised
    r = client.post("/api/knowledge/documents", headers=h, files={"file": ("../../etc/passwd.txt", b"some valid text content here")})
    assert r.status_code == 201 and "/" not in r.json()["filename"]


def test_delete_removes_vectors(client, kb_tenant):
    h = kb_tenant["h"]
    doc = client.get("/api/knowledge/documents", headers=h).json()[0]
    assert client.delete(f"/api/knowledge/documents/{doc['id']}", headers=h).status_code == 200
    assert client.post("/api/knowledge/search", headers=h, json={"query": "refund"}).json() == []


def test_ask_rag(client, kb_tenant):
    r = client.post("/api/knowledge/ask", headers=kb_tenant["h"], json={"question": "What is the refund policy?"})
    assert r.status_code == 200 and r.json()["grounded"] and r.json()["sources"][0]["filename"] == "policies.txt"
    r = client.post("/api/knowledge/ask", headers=kb_tenant["h"], json={"question": "zzzqqq xylophone"})
    assert r.json()["grounded"] is False


def test_index_rebuilds_from_database_when_vector_files_are_lost(client, kb_tenant):
    import shutil
    from app.config import settings
    h = kb_tenant["h"]
    assert client.post("/api/knowledge/search", headers=h, json={"query": "refund"}).json()
    shutil.rmtree(settings.vector_dir, ignore_errors=True)  # simulate ephemeral disk wipe
    again = client.post("/api/knowledge/search", headers=h, json={"query": "refund policy"}).json()
    assert again and again[0]["filename"] == "policies.txt"
