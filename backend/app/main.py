"""FastAPI application for the AI Video Studio foundation."""

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI(title=os.getenv("APP_NAME", "AI Video Studio API"))

origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Return a small response so the frontend can check API availability."""
    return {"status": "ok", "service": "ai-video-studio-api"}
