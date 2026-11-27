"""Shared pytest configuration for test-safe settings."""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Force test settings before backend modules are imported. This keeps tests
# away from the real development database and real secrets.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-not-for-production"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"
os.environ["GEMINI_API_KEY"] = ""
os.environ["GEMINI_MODEL"] = "test-model"
os.environ["BACKEND_BASE_URL"] = "http://127.0.0.1:8000"
os.environ["FRONTEND_ORIGIN"] = "http://localhost:8501"
os.environ["MAX_UPLOAD_MB"] = "5"
os.environ["MAX_SOURCE_CHARS"] = "30000"


@pytest.fixture
def client():
    """Provide a FastAPI TestClient for future API tests."""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client
