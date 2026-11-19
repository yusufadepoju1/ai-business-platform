# Testing

```powershell
.\scripts\test.ps1          # or: python -m pytest tests -v
```
Tests use a temporary SQLite database and a scripted **fake LLM** that follows the agents' JSON prompt contract. The LangGraph routing, retrieval, CRM tools, escalation and webhooks all run for real; only the Groq call is replaced. To run against PostgreSQL: `$env:TEST_DATABASE_URL="postgresql://user:pass@localhost/test_db"; pytest tests`.

## Automated coverage (31 tests)
- Auth: register, login, duplicate email, weak password, JWT required, bcrypt hash stored, rate limiting.
- Tenant isolation: another business gets 404 on customers, leads, documents, conversations, replies; lists and vector search never leak; n8n secrets cannot touch other tenants' leads.
- RBAC: agent role cannot edit business, upload, create automations or add members; deactivated users are locked out.
- Documents: TXT/DOCX/PDF ingestion + semantic search, rejection of bad types / fake PDFs / fake DOCX / empty / binary / oversize files, filename sanitising, deletion removes vectors.
- Agents: grounded answers, conversation memory, escalation + signed webhook + header auth, AI silence once a human owns a conversation, human-request handoff, sales lead creation with price taken from the uploaded document, no invented pricing, disabled-agent handoff, graceful behaviour with no LLM key.
- CRM CRUD / search / filters / cascades, follow-ups, automation validation (including SSRF guard), failed webhooks logged.
- Integrations: secrets encrypted and masked, WhatsApp verify + signature check + receive + de-duplication, widget chat + human-reply polling + CORS, API-key lead creation, n8n callbacks, analytics matching the database.

## UI smoke tests (optional, Node 18+)
`tests/ui_smoke/` loads the real frontend in jsdom against a running server and checks every dashboard page renders live data, plus form validation, registration, login errors, the agent-test chat and add-customer flows:
```powershell
cd tests\ui_smoke; npm init -y; npm i jsdom
# start the app (.\scripts\run.ps1 -Demo), then:
node smoke.js; node flows.js
```
These check DOM behaviour, not visual layout. Review the pages in a real browser before launch.

## What has and has not been verified
| Area | Status |
|---|---|
| Backend API, tenancy, RBAC, RAG, agents (fake LLM), CRM, webhooks, analytics | Automated, passing on SQLite **and** PostgreSQL 16 |
| Alembic migration | Applied and `alembic check` clean on SQLite and PostgreSQL 16 |
| Production start (`alembic upgrade head && gunicorn ...`, secret guard, `/health`) | Run locally |
| Frontend pages and flows | jsdom smoke tests against the live server |
| **Live Groq calls** | **Not tested** - needs your `GROQ_API_KEY` |
| **sentence-transformers embeddings** | **Not tested** - build sandbox cannot download the model; hashing fallback was tested |
| **WhatsApp Cloud API send/receive** | **Logic tested with mocked HTTP**; not tested against Meta - needs your credentials |
| **SMTP delivery** | **Not tested live**; "not configured" path tested |
| **n8n workflow import** | JSON structure validated; **not imported into n8n** here |
| **Render deployment** | `render.yaml` syntax-checked; **not deployed** |
| Visual design in a real browser | Not verified (no browser in build sandbox) |
