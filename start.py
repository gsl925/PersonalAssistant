"""Launch script for the Personal AI Assistant.

Services required before running:
  - PostgreSQL 16  (free Windows installer: https://www.postgresql.org/download/windows/)
  - Qdrant         (free Windows binary:   https://github.com/qdrant/qdrant/releases)

No Redis or Celery needed — APScheduler runs inside the FastAPI process.
"""
import sys
from pathlib import Path

import uvicorn

BASE_DIR = Path(__file__).parent


def check_env() -> None:
    if not (BASE_DIR / ".env").exists():
        print("ERROR: .env file not found. Copy .env.example to .env and fill in values.")
        sys.exit(1)


if __name__ == "__main__":
    check_env()
    print("Starting Personal AI Assistant on http://localhost:8000 …")
    print("  API docs : http://localhost:8000/api/docs")
    print("  Dashboard: http://localhost:8000/dashboard  (if frontend is built)")
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
