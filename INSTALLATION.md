# Installation (Windows PowerShell)

## Prerequisites
- Python 3.11 or newer (python.org, tick "Add to PATH")
- PostgreSQL 14+ (optional for a first look; recommended)
- Node.js is only needed to run the optional UI smoke tests in `tests/ui_smoke`

## 1. Setup
```powershell
cd AI_Business_Automation_Platform
.\scripts\setup.ps1
```
If PowerShell blocks scripts: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.
The first install downloads PyTorch (via `sentence-transformers`), which is large. To skip it, remove the last two lines of `requirements.txt` and set `EMBEDDING_PROVIDER=hashing` in `.env`.

## 2. PostgreSQL
```powershell
psql -U postgres -c "CREATE DATABASE ai_business;"
```
Set in `.env`: `DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/ai_business`

## 3. Groq
Set `GROQ_API_KEY=` in `.env`. Never commit `.env`.

## 4. Run
```powershell
.\scripts\run.ps1            # migrations + server
.\scripts\run.ps1 -Demo      # also loads the demo workspace
```
Open http://localhost:8000 . Health check: http://localhost:8000/health . API docs: http://localhost:8000/api/docs .

## 5. Manual commands (if you prefer)
```powershell
.\.venv\Scripts\Activate.ps1
alembic upgrade head
python scripts\seed_demo.py --reset
uvicorn app.main:app --reload
```

## Troubleshooting
- `Embeddings ... hashing fallback` in the log: sentence-transformers or its model could not be loaded. Search still works (keyword-oriented). Install it / allow Hugging Face downloads for semantic embeddings.
- Switching embedding provider rebuilds each business's FAISS index automatically on next use.
- `SECRET_KEY must be set` in production: set a long random value.
