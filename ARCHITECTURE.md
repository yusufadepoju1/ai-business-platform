# Architecture

```
Browser (static HTML/CSS/JS, Chart.js) --/api--> FastAPI app ----> PostgreSQL (SQLAlchemy, Alembic)
Website widget / API clients / WhatsApp --------^        |------> FAISS index per business (data/vectors)
n8n <--signed webhooks-- automation service <------------|------> Groq (LangChain ChatGroq)
n8n --X-Webhook-Secret callbacks--> /api/webhooks/n8n    |------> SMTP, WhatsApp Graph API
```

## Layout
- `app/routers/` HTTP layer (auth, business, knowledge, agents, crm, conversations, automations, integrations, analytics, public, webhooks).
- `app/services/` business logic: `documents` (validate/extract/chunk), `embeddings`, `vectorstore`, `rag`, `llm`, `agent_graph` (LangGraph), `conversation`, `tools` (CRM actions), `automation`, `emailer`, `whatsapp`.
- `app/models.py` all tables; `app/deps.py` auth, RBAC and the tenant-scoped `get_owned` fetch.
- `frontend/` static SPA (`app.html` with hash routes) + landing/login/register + `widget.js`.
- `alembic/` migrations; `n8n_workflows/` exports; `scripts/` PowerShell scripts, seed, packaging.

## Multi-tenancy
Every tenant table has `business_id`. The JWT carries the user, and `current_user` verifies the user's business matches. List queries filter by `user.business_id`; item routes use `get_owned()` which returns 404 for foreign IDs. Vector indexes are separate files per business and search results are re-filtered by `business_id` in SQL. Public endpoints resolve the business from a public key; n8n callbacks resolve it from the webhook secret and then re-check ownership.

## Agent workflow (LangGraph)
```
classify --human_request--> handoff --> finalize
   |-- error --> finalize
   '-- retrieve --+-- sales (if enabled) --> sales_agent --> crm_tools --> finalize
                  '-- support ---------> support_agent --> support_tools --unresolved--> handoff --> finalize
```
- **Memory**: last 12 stored messages are replayed to the LLM; escalated conversations stay with humans (AI silent).
- **Grounding**: support answers only from retrieved context; sales quotes prices only if present in context (prompted and covered by a test with a fake LLM; model compliance with a real LLM depends on the model and should be reviewed with your own documents).
- **CRM tools**: upsert customer, create/update lead only when contact details and requirement info exist, schedule follow-up, fire `new_lead`/`lead_qualified`.
- **Handoff**: creates an escalation, marks the conversation, fires `human_escalation` (webhook + email).
- **Failure**: no key or provider error -> `error` in state -> user sees an unavailable message, conversation flagged unresolved, nothing fabricated.

## Retrieval
Chunks (800 chars, 120 overlap, paragraph-aware) are stored in SQL and embedded into a FAISS `IndexIDMap2(IndexFlatIP)` using chunk IDs as vector IDs. The provider name is saved beside the index; if it changes the index is rebuilt from SQL. Default embeddings: `all-MiniLM-L6-v2`; fallback: a signed-hashing lexical embedder (not neural).

## Security
bcrypt hashes, HS256 JWT, Fernet encryption of WhatsApp/SMTP/auth-header secrets, API keys stored as SHA-256 hashes, upload validation (extension, size, magic bytes), filename sanitising, outbound webhook HMAC signatures, SSRF guard for webhook targets, WhatsApp signature check, per-IP rate limits (in-memory, per process), security headers, no secrets in the repo.

Known limits: rate limits and WhatsApp de-duplication are per process; FAISS indexes need a persistent disk and a single writer process (the Render config uses one worker); documents are processed synchronously in the upload request; JWTs are in `localStorage` (consider httpOnly cookies for stricter deployments).
