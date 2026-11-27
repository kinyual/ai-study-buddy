"""Minimal FastAPI application for AI Study Buddy."""

from fastapi import FastAPI

from .api.auth import router as auth_router

app = FastAPI(title="AI Study Buddy", version="0.1.0")
app.include_router(auth_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Return a small response used to check that the backend is running."""
    return {"status": "healthy"}
