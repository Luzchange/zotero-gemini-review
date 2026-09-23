import sys
import os

# Add parent directory to sys.path so app package can be resolved
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app.main import app

# Vercel serverless function entrypoint
__all__ = ["app"]
