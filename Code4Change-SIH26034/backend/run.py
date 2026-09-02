"""
run.py – Development launcher.

Usage:
    python run.py

This starts the uvicorn server with auto-reload enabled.
For production use uvicorn directly:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
"""

import uvicorn
from app.config import APP_HOST, APP_PORT, DEBUG

if __name__ == "__main__":
    print(f"Starting Code4Change backend on http://{APP_HOST}:{APP_PORT}")
    print(f"Interactive API docs: http://{APP_HOST}:{APP_PORT}/docs")
    uvicorn.run(
        "app.main:app",
        host=APP_HOST,
        port=APP_PORT,
        reload=DEBUG,           # auto-reload on file changes in dev mode
        reload_dirs=["app"],    # only watch the app/ directory
        log_level="info",
    )
