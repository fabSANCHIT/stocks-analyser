"""
Vercel entry point.

Vercel's Python runtime looks for a module-level ASGI app called `app`. The
real application lives in backend/app, so this puts that on the import path
and re-exports it. vercel.json makes sure backend/ and data/ are bundled.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402,F401
