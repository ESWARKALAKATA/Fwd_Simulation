from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.api.routes import router
from app.db.session import engine
from app.db.models import Base
from app.config import settings

app = FastAPI(title="GenAI Backend Service", version="0.1.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.on_event("startup")
async def startup():
    # Create tables for demo purposes
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Create pgvector-backed table for code embeddings (if not exists)
        if settings.ENABLE_EMBED_INDEX:
            await conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS code_chunks (
                        id SERIAL PRIMARY KEY,
                        repo TEXT NOT NULL,
                        path TEXT NOT NULL,
                        content TEXT NOT NULL,
                        embedding vector({settings.EMBEDDING_DIM}),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );
                    """
                )
            )

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
