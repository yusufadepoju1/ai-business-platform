import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import settings
from .database import Base, SessionLocal, engine
from .logging_conf import setup_logging
from .routers import (agents, analytics, auth, automations, business, conversations, crm, integrations, knowledge,
                      public, webhooks)

setup_logging()
log = logging.getLogger("app")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_production and settings.secret_key.startswith("dev-only"):
        raise RuntimeError("SECRET_KEY must be set to a strong random value in production.")
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
    if not settings.groq_api_key:
        log.warning("GROQ_API_KEY is not set: AI agents will report 'not configured' until it is provided.")
    yield


app = FastAPI(title="AI Business Automation Platform", version="1.0.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

if settings.cors_list:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def public_cors_and_headers(request: Request, call_next):
    public = request.url.path.startswith("/api/public/") or request.url.path == "/widget.js"
    if public and request.method == "OPTIONS":
        resp = Response(status_code=204)
    else:
        resp = await call_next(request)
    if public:  # key-based endpoints, no cookies: safe to allow any origin (the embedded widget)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN" if not public else "ALLOWALL")
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Something went wrong on the server. Please try again."}, status_code=500)


@app.get("/health", tags=["system"])
def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok", "ai_configured": bool(settings.groq_api_key)}
    except Exception as exc:
        return JSONResponse({"status": "degraded", "database": f"error: {type(exc).__name__}"}, status_code=503)


for r in (auth, business, knowledge, agents, crm, conversations, automations, integrations, analytics, public, webhooks):
    app.include_router(r.router)

if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
