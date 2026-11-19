from tests.conftest import register


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_register_login_me(client):
    h, user, email = register(client, "Login Co")
    assert user["role"] == "owner"
    r = client.post("/api/auth/login", json={"email": email, "password": "StrongPass123"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["email"] == email and me["business_name"] == "Login Co"


def test_login_failures_and_duplicates(client, tenant):
    assert client.post("/api/auth/login", json={"email": tenant["email"], "password": "wrong-password"}).status_code == 401
    dup = client.post("/api/auth/register", json={"business_name": "X Co", "full_name": "Y Z", "email": tenant["email"], "password": "StrongPass123"})
    assert dup.status_code == 409
    short = client.post("/api/auth/register", json={"business_name": "X Co", "full_name": "Y Z", "email": "a@b.co", "password": "short"})
    assert short.status_code == 422


def test_requires_auth(client):
    for path in ["/api/customers", "/api/leads", "/api/knowledge/documents", "/api/analytics/overview", "/api/business"]:
        assert client.get(path).status_code == 401
    assert client.get("/api/customers", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_password_is_hashed(client, tenant):
    from app.database import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == tenant["email"]).one()
        assert u.hashed_password != "StrongPass123" and u.hashed_password.startswith("$2")


def test_tenant_isolation(client, kb_tenant, tenant2):
    a, b = kb_tenant["h"], tenant2["h"]
    cust = client.post("/api/customers", headers=a, json={"name": "Secret Customer", "email": "secret@x.com"}).json()
    lead = client.post("/api/leads", headers=a, json={"customer_id": cust["id"], "title": "Big deal"}).json()
    doc = client.get("/api/knowledge/documents", headers=a).json()[0]
    # B cannot see or touch A's records
    assert client.get(f"/api/customers/{cust['id']}", headers=b).status_code == 404
    assert client.put(f"/api/customers/{cust['id']}", headers=b, json={"name": "hacked"}).status_code == 404
    assert client.delete(f"/api/customers/{cust['id']}", headers=b).status_code == 404
    assert client.get(f"/api/leads/{lead['id']}", headers=b).status_code == 404
    assert client.patch(f"/api/leads/{lead['id']}", headers=b, json={"status": "lost"}).status_code == 404
    assert client.delete(f"/api/knowledge/documents/{doc['id']}", headers=b).status_code == 404
    assert client.get(f"/api/knowledge/documents/{doc['id']}", headers=b).status_code == 404
    assert client.get("/api/customers", headers=b).json()["total"] == 0
    assert client.get("/api/leads", headers=b).json()["total"] == 0
    assert client.get("/api/knowledge/documents", headers=b).json() == []
    # B cannot create a lead for A's customer
    assert client.post("/api/leads", headers=b, json={"customer_id": cust["id"]}).status_code == 404
    # vector search never crosses tenants
    assert client.post("/api/knowledge/search", headers=b, json={"query": "refund policy"}).json() == []
    assert len(client.post("/api/knowledge/search", headers=a, json={"query": "refund policy"}).json()) >= 1
    # conversations isolated
    client.post("/api/agents/test", headers=a, json={"message": "refund?"})
    cid = client.get("/api/conversations?include_test=true", headers=a).json()["items"][0]["id"]
    assert client.get(f"/api/conversations/{cid}", headers=b).status_code == 404
    assert client.post(f"/api/conversations/{cid}/reply", headers=b, json={"content": "x"}).status_code == 404
    assert client.get("/api/conversations?include_test=true", headers=b).json()["total"] == 0
    assert client.get("/api/analytics/overview", headers=b).json()["totals"]["customers"] == 0


def test_role_based_access(client, tenant):
    h = tenant["h"]
    r = client.post("/api/team", headers=h, json={"full_name": "Rep One", "email": "rep1@example.com", "password": "RepPass12345", "role": "agent"})
    assert r.status_code == 201
    tok = client.post("/api/auth/login", json={"email": "rep1@example.com", "password": "RepPass12345"}).json()["access_token"]
    rep = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/customers", headers=rep).status_code == 200
    assert client.put("/api/business", headers=rep, json={"name": "Hacked Name"}).status_code == 403
    assert client.post("/api/team", headers=rep, json={"full_name": "X Y", "email": "z@z.co", "password": "PassPass1234"}).status_code == 403
    assert client.post("/api/knowledge/documents", headers=rep, files={"file": ("a.txt", b"hello world text", "text/plain")}).status_code == 403
    assert client.put("/api/agents/support", headers=rep, json={"name": "x"}).status_code == 403
    assert client.post("/api/automations", headers=rep, json={"name": "nn", "event": "new_lead", "target_url": "http://localhost:5678/x"}).status_code == 403
    # deactivated users lose access
    rid = r.json()["id"]
    client.patch(f"/api/team/{rid}", headers=h, json={"is_active": False})
    assert client.get("/api/customers", headers=rep).status_code == 401


def test_rate_limit(client, monkeypatch):
    from app import ratelimit
    from app.config import settings
    ratelimit.reset_limits()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    codes = [client.post("/api/auth/login", json={"email": "nobody@x.com", "password": "whatever123"}).status_code for _ in range(25)]
    assert 429 in codes
    ratelimit.reset_limits()
