import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings, get_credentials
from app.routers import zotero_router, review_router, documents_router

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

# Search multiple candidate directories for templates
candidate_template_dirs = [
    templates_dir,
    os.path.join(os.path.dirname(base_dir), "app", "templates"),
    os.path.join(os.getcwd(), "app", "templates"),
    os.path.join(os.getcwd(), "templates"),
    base_dir,
]
active_templates_dir = next((d for d in candidate_template_dirs if os.path.isdir(d) and os.path.exists(os.path.join(d, "index.html"))), None)

templates = Jinja2Templates(directory=active_templates_dir) if active_templates_dir else None

# Mount static files safely only if directory exists
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
elif os.path.isdir(os.path.join(os.getcwd(), "public", "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(os.getcwd(), "public", "static")), name="static")

# Register routers
app.include_router(zotero_router.router)
app.include_router(review_router.router)
app.include_router(documents_router.router)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the interactive literature review dashboard."""
    creds = get_credentials(request)
    context = {
        "has_gemini_key": bool(creds.get("gemini_key")),
        "has_zotero_creds": bool(creds.get("zotero_key") and creds.get("zotero_user_id")),
        "default_model": creds.get("gemini_model", "gemini-3.6-flash")
    }

    if templates:
        try:
            return templates.TemplateResponse(request=request, name="index.html", context=context)
        except Exception as e:
            logger.warning(f"Template rendering failed: {e}")

    # Fallback: direct file read if templates engine wasn't resolved
    candidate_files = [
        os.path.join(templates_dir, "index.html"),
        os.path.join(base_dir, "templates", "index.html"),
        os.path.join(os.getcwd(), "app", "templates", "index.html"),
        os.path.join(os.getcwd(), "templates", "index.html"),
        os.path.join(os.getcwd(), "public", "index.html"),
    ]
    for p in candidate_files:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return HTMLResponse(f.read())

    return HTMLResponse("<h2>GResearch Studio</h2><p>index.html not found in server bundle.</p>", status_code=500)

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
        "gemini_base_url": creds.get("gemini_base_url"),
        "zotero_configured": bool(creds.get("zotero_key") and creds.get("zotero_user_id")),
        "zotero_user_id": creds.get("zotero_user_id") if creds.get("zotero_user_id") else None,
        "library_type": creds.get("zotero_library_type")
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
