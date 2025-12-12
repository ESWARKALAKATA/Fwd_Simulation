from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # LLM API Keys
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    PINECONE_API_KEY: Optional[str] = None
    
    # GitHub
    GITHUB_TOKEN: Optional[str] = None
    # Placeholder for the target repo, e.g., "owner/repo"
    GITHUB_TARGET_REPO: str = "fastapi/fastapi" 

    # Retrieval / Embeddings
    HYBRID_RETRIEVAL: bool = True  # if True combine lexical + vector
    EMBEDDING_MODEL: str = "gemini-embedding-001"  # Default to Gemini embedding
    EMBEDDING_PROVIDER: str = "gemini"  # 'openai' | 'gemini'
    EMBEDDING_DIM: int = 768  # gemini-embedding-001 output dimension (adjust if Google updates)
    ENABLE_EMBED_INDEX: bool = True  # allow vector search if table populated

    @property
    def github_repo_name(self) -> str:
        """
        Extracts 'owner/repo' from GITHUB_TARGET_REPO if it's a full URL.
        """
        repo = self.GITHUB_TARGET_REPO
        if repo.startswith("https://github.com/"):
            return repo.replace("https://github.com/", "").strip("/")
        return repo

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/dbname"

    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
