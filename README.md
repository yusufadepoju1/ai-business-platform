# Autopilot - AI Business Automation Platform

A multi-tenant SaaS where businesses register a workspace, upload their documents, configure AI support and sales assistants, manage customers and leads, and automate follow-ups through n8n, WhatsApp, email and a REST API.

## Features
- **Auth & tenancy**: JWT login, bcrypt password hashing, one workspace per business, roles (`owner`, `admin`, `agent`), strict `business_id` isolation on every query.
- **Knowledge base**: PDF / TXT / DOCX upload with validation, text extraction, chunking, embeddings, per-business FAISS index, semantic search, RAG question answering.
- **Support agent**: answers only from the business's documents, keeps conversation history, flags unresolved questions, escalates to a human.
- **Sales agent**: recommends from verified data, quotes prices only found in documents, captures contact details, qualifies (hot/warm/cold), creates CRM leads and follow-ups.
- **LangGraph orchestration**: intent classification -> routing -> retrieval -> support/sales tools -> CRM tools -> human handoff, with memory from stored messages.
- **CRM**: customers, leads, status tracking, follow-ups, search/filter, conversation history.
- **Automation**: signed outbound webhooks (n8n or any REST endpoint), inbound n8n callbacks, email alerts, 5 importable n8n workflows.
- **Channels**: embeddable web chat widget, WhatsApp Business Cloud API, SMTP email, API-key REST API.
- **Analytics**: all numbers computed from the database (totals, rates, daily and weekly series) with Chart.js.
- **Dashboard**: 15 pages (landing, register, login, dashboard, business settings, knowledge base, AI agents, agent testing, CRM & leads, customers, conversations, automations, integrations, analytics, user settings).

## Honesty rules built into the product
- No GROQ key -> agents say they are unavailable. They never return canned text as "AI output".
- Integrations show "not connected" until real credentials are saved. Email attempts without SMTP are logged as `skipped`.
- Demo data (`scripts/seed_demo.py`) lives in a separate workspace flagged `is_demo`, with a visible banner.

## Technology
Python 3.11+, FastAPI, SQLAlchemy 2, Pydantic 2, Alembic, PostgreSQL (SQLite fallback for quick local runs), Groq via LangChain (`langchain-groq`), LangGraph, FAISS, sentence-transformers (with a lightweight hashing fallback), pypdf, python-docx, n8n, vanilla HTML/CSS/JS, Chart.js, Pytest.

## Quick start (Windows PowerShell)
```powershell
cd AI_Business_Automation_Platform
.\scripts\setup.ps1          # venv + dependencies + .env with a generated SECRET_KEY
notepad .env                 # set DATABASE_URL and GROQ_API_KEY
.\scripts\run.ps1 -Demo      # migrate, load demo workspace, start on http://localhost:8000
```
Demo login: `demo@example.com` / `DemoPass123!`. Omit `-Demo` for a clean start and register your own business.
Full details: [INSTALLATION.md](INSTALLATION.md).

## Configure the pieces
- **Groq**: create a key at https://console.groq.com/keys, put it in `.env` as `GROQ_API_KEY`, restart. The Integrations page shows connected/not connected.
- **PostgreSQL**: `DATABASE_URL=postgresql://user:pass@localhost:5432/ai_business` (create the database first), then `alembic upgrade head` (run.ps1 does this). Without `DATABASE_URL` the app uses `dev.db` (SQLite) for development only.
- **Backend / frontend**: one process serves both. The API is under `/api`, the frontend is static files from `frontend/` at `/`. Interactive API docs: `/api/docs`.
- **n8n**: see [DEPLOYMENT.md](DEPLOYMENT.md#n8n) and `n8n_workflows/`.
- **WhatsApp / email**: Integrations page, instructions in [DEPLOYMENT.md](DEPLOYMENT.md#whatsapp).

## Screenshots
Run with `-Demo`, open http://localhost:8000/app.html and capture: Dashboard, Knowledge base, Agent testing, CRM & leads, Conversations, Analytics. Save them in `docs/screenshots/` and link them here. (None are bundled because they were not captured in the build environment.)

## Local development
```powershell
.\scripts\test.ps1                       # pytest (31 tests)
python scripts\make_n8n_workflows.py     # regenerate n8n workflow JSON
alembic revision --autogenerate -m "change"   # after editing app\models.py
```

## Deploy / GitHub
See [DEPLOYMENT.md](DEPLOYMENT.md) for the GitHub upload steps and the Render Blueprint (`render.yaml`).

## Documentation
[INSTALLATION](INSTALLATION.md) | [API](API_DOCUMENTATION.md) | [ARCHITECTURE](ARCHITECTURE.md) | [DEPLOYMENT](DEPLOYMENT.md) | [ENVIRONMENT_VARIABLES](ENVIRONMENT_VARIABLES.md) | [TESTING](TESTING.md)
