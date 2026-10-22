# Copy to .env for running outside Docker (uvicorn app.main:app --reload).
DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app
LOG_LEVEL=INFO
# JSON list
CORS_ORIGINS=["*"]
