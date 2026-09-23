import sys
import os
import traceback

# Ensure root directory and current directories are on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
for p in [root_dir, current_dir, os.getcwd()]:
    if p and p not in sys.path:
        sys.path.insert(0, p)

try:
    from app.main import app
except Exception as e:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="GResearch Error Diagnostic")
    err_trace = traceback.format_exc()

    @app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"])
    async def vercel_startup_error(path_name: str = ""):
        return HTMLResponse(
            f"""
            <!DOCTYPE html>
            <html>
            <head>
              <meta charset="utf-8">
              <title>GResearch - Function Startup Error</title>
              <style>
                body {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; background: #fff1f2; color: #9f1239; padding: 2rem; }}
                .card {{ background: white; border: 1px solid #fecdd3; border-radius: 8px; padding: 1.5rem; max-width: 900px; margin: 0 auto; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }}
                h2 {{ margin-top: 0; color: #881337; }}
                pre {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 1rem; overflow-x: auto; font-size: 13px; color: #334155; }}
              </style>
            </head>
            <body>
              <div class="card">
                <h2>GResearch Vercel Function Startup Error</h2>
                <p>The application encountered an exception while importing <code>app.main</code>:</p>
                <pre>{err_trace}</pre>
                <p style="font-size: 12px; color: #64748b;">sys.path: {sys.path}</p>
              </div>
            </body>
            </html>
            """,
            status_code=500
        )

__all__ = ["app"]
