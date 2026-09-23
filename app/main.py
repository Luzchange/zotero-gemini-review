import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings, get_credentials
from app.routers import zotero_router, review_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("gresearch")

app = FastAPI(
    title="GResearch - AI Literature Review Studio & API",
    description="Intelligent academic literature review assistant connecting Google Gemini with Zotero.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Ensure any unhandled server error returns clean JSON rather than raw text."""
    logger.exception(f"Unhandled server error at {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Server Error: {str(exc)}"}
    )

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static and Templates
base_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(base_dir, "static")
templates_dir = os.path.join(base_dir, "templates")

os.makedirs(static_dir, exist_ok=True)
os.makedirs(templates_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

# Register routers
app.include_router(zotero_router.router)
app.include_router(review_router.router)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the interactive literature review dashboard."""
    creds = get_credentials(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "has_gemini_key": bool(creds.get("gemini_key")),
            "has_zotero_creds": bool(creds.get("zotero_key") and creds.get("zotero_user_id")),
            "default_model": creds.get("gemini_model", "gemini-2.5-flash")
        }
    )

@app.get("/api/health")
async def health_check(request: Request):
    """Health check endpoint displaying configuration readiness."""
    creds = get_credentials(request)
    return {
        "status": "online",
        "app": "GResearch",
        "version": "1.0.0",
        "gemini_configured": bool(creds.get("gemini_key")),
        "gemini_model": creds.get("gemini_model"),
        "zotero_configured": bool(creds.get("zotero_key") and creds.get("zotero_user_id")),
        "zotero_user_id": creds.get("zotero_user_id") if creds.get("zotero_user_id") else None,
        "library_type": creds.get("zotero_library_type")
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
