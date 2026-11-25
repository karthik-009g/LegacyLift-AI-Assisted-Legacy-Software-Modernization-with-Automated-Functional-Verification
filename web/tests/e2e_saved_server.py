"""Serve saved local evidence for a read-only browser walkthrough; start no job worker."""

import os
from pathlib import Path

import uvicorn

from legacylift.workbench.api import create_app

for key in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(key, None)

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    os.environ["LEGACYLIFT_WEB_DIST"] = str(root / "web/dist")
    uvicorn.run(create_app(root / ".legacylift", start_jobs=False), host="127.0.0.1", port=8012)
