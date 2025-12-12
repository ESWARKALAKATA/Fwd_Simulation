"""AST-based GitHub repository indexer with intelligent chunking."""
from __future__ import annotations
import ast
import base64
import httpx
from typing import List, Tuple
from sqlalchemy import text
from app.config import settings
from app.llm.embeddings import get_embedding
from app.db.session import AsyncSessionLocal
from app.utils.logger import get_indexer_logger

logger = get_indexer_logger()


async def index_github_repo_ast(
    repo: str | None = None, 
    branch: str = "HEAD", 
    file_limit: int = 150
) -> None:
    """Index GitHub repository using AST parsing for intelligent chunking."""
    repo = repo or settings.github_repo_name
    
    if not settings.GITHUB_TOKEN:
        raise ValueError("[Indexer] GITHUB_TOKEN required in .env")
    if not settings.GEMINI_API_KEY and settings.EMBEDDING_PROVIDER == "gemini":
        raise ValueError("[Indexer] GEMINI_API_KEY required for embedding generation")
    
    logger.info(f"Starting indexing for repo: {repo}")
    logger.info(f"Embedding config: {settings.EMBEDDING_PROVIDER}/{settings.EMBEDDING_MODEL} ({settings.EMBEDDING_DIM}D)")
    
    owner, name = repo.split("/", 1)
    chunks_to_insert: List[Tuple[str, str, str, str]] = []
    
    async with httpx.AsyncClient(timeout=90) as client:
        headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"}
        tree_url = f"https://api.github.com/repos/{owner}/{name}/git/trees/{branch}?recursive=1"
        
        logger.info("Fetching file tree from GitHub...")
        tree_resp = await client.get(tree_url, headers=headers)
        if tree_resp.status_code != 200:
            raise RuntimeError(f"Tree fetch error {tree_resp.status_code}: {tree_resp.text[:200]}")
        
        tree = tree_resp.json()
        py_paths = [
            item["path"] 
            for item in tree.get("tree", []) 
            if item.get("type") == "blob" and item["path"].endswith(".py")
        ]
        py_paths = py_paths[:file_limit]
        logger.info(f"Found {len(py_paths)} Python files (limit: {file_limit})")
        
        for idx, path in enumerate(py_paths, 1):
            contents_url = f"https://api.github.com/repos/{owner}/{name}/contents/{path}"
            
            try:
                c_resp = await client.get(contents_url, headers=headers)
                if c_resp.status_code != 200:
                    logger.warning(f"[{idx}/{len(py_paths)}] {path} - Fetch error {c_resp.status_code}")
                    continue
                
                c_data = c_resp.json()
                encoded = c_data.get("content")
                if not encoded:
                    logger.warning(f"[{idx}/{len(py_paths)}] {path} - No content")
                    continue
                
                raw = base64.b64decode(encoded).decode("utf-8", errors="ignore")
                
                chunks = _chunk_code_ast(raw, path)
                if not chunks:
                    logger.warning(f"[{idx}/{len(py_paths)}] {path} - No chunks extracted")
                    continue
                
                for chunk_content in chunks:
                    embedding = await get_embedding(chunk_content)
                    
                    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
                    
                    if len(embedding) != settings.EMBEDDING_DIM:
                        logger.warning(f"[{idx}/{len(py_paths)}] {path} - Embedding dim={len(embedding)}, expected {settings.EMBEDDING_DIM}")
                    
                    chunks_to_insert.append((repo, path, chunk_content, embedding_str))
                
                logger.info(f"[{idx}/{len(py_paths)}] {path} - {len(chunks)} chunks processed")
            
            except Exception as e:
                logger.error(f"[{idx}/{len(py_paths)}] {path} - Error: {e}")
                continue
    
    # Verify code_chunks table embedding dimension matches current setting; recreate if mismatch
    async with AsyncSessionLocal() as dim_session:
        try:
            dim_result = await dim_session.execute(
                text("SELECT atttypmod FROM pg_attribute WHERE attrelid = 'code_chunks'::regclass AND attname='embedding'")
            )
            row = dim_result.fetchone()
            if row:
                existing_dim = row[0]  # pgvector stores dimension directly in typmod
                if existing_dim != settings.EMBEDDING_DIM:
                    logger.warning(f"Dimension mismatch: existing={existing_dim} expected={settings.EMBEDDING_DIM}. Recreating table.")
                    await dim_session.execute(text("DROP TABLE code_chunks"))
                    await dim_session.commit()
                    await dim_session.execute(text(f"""
                        CREATE TABLE code_chunks (
                            id SERIAL PRIMARY KEY,
                            repo TEXT NOT NULL,
                            path TEXT NOT NULL,
                            content TEXT NOT NULL,
                            embedding vector({settings.EMBEDDING_DIM}),
                            updated_at TIMESTAMPTZ DEFAULT NOW()
                        );
                    """))
                    await dim_session.commit()
            else:
                # Table might not exist yet
                await dim_session.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS code_chunks (
                        id SERIAL PRIMARY KEY,
                        repo TEXT NOT NULL,
                        path TEXT NOT NULL,
                        content TEXT NOT NULL,
                        embedding vector({settings.EMBEDDING_DIM}),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """))
                await dim_session.commit()
        except Exception as e:
            logger.error(f"Dimension check failed: {e}")
            await dim_session.rollback()

    logger.info(f"Inserting {len(chunks_to_insert)} chunks into pgvector table...")
    
    async with AsyncSessionLocal() as session:
        for repo_val, path_val, content_val, embedding_str_val in chunks_to_insert:
            await session.execute(
                text(
                    """
                    INSERT INTO code_chunks (repo, path, content, embedding) 
                    VALUES (:repo, :path, :content, :embedding)
                    """
                ),
                {
                    "repo": repo_val,
                    "path": path_val,
                    "content": content_val,
                    "embedding": embedding_str_val
                },
            )
        await session.commit()
    
    logger.info(f"Successfully indexed {len(chunks_to_insert)} code chunks")


def _chunk_code_ast(code: str, filepath: str) -> List[str]:
    """Parse Python code with AST and extract function/class chunks."""
    chunks: List[str] = []
    
    try:
        tree = ast.parse(code)
        
        for node in ast.walk(tree):
            # Extract functions (only top-level, not nested)
            if isinstance(node, ast.FunctionDef):
                if _is_top_level(node, tree):
                    chunk = ast.get_source_segment(code, node)
                    if chunk:
                        chunks.append(_truncate(chunk, 4000))
            
            # Extract classes (with methods included)
            elif isinstance(node, ast.ClassDef):
                if _is_top_level(node, tree):
                    chunk = ast.get_source_segment(code, node)
                    if chunk:
                        chunks.append(_truncate(chunk, 4000))
        
        # If no top-level definitions found, chunk by size
        if not chunks:
            return _slice_large(code)
        
        return chunks
    
    except SyntaxError:
        # Fallback: regex-based chunking for malformed files
        return _chunk_code_regex(code)


def _is_top_level(node: ast.AST, tree: ast.Module) -> bool:
    """Check if node is a top-level definition."""
    for item in tree.body:
        if item == node:
            return True
        # Check if node is a direct child method of a top-level class
        if isinstance(item, ast.ClassDef):
            for child in item.body:
                if child == node:
                    return True
    return False


def _chunk_code_regex(code: str) -> List[str]:
    """Fallback regex-based chunking (original logic for malformed Python files)."""
    import re
    PY_FUNC_RE = re.compile(r"^(def|class)\s+\w+.*:", re.MULTILINE)
    matches = list(PY_FUNC_RE.finditer(code))
    if not matches:
        return _slice_large(code)
    
    chunks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(code)
        segment = code[start:end].strip()
        if segment:
            chunks.append(_truncate(segment, 4000))
    return chunks or _slice_large(code)


def _slice_large(code: str, size: int = 3500) -> List[str]:
    """Slice code into fixed-size chunks."""
    return [code[i : i + size] for i in range(0, len(code), size)]


def _truncate(text: str, max_len: int = 4000) -> str:
    """Safely truncate text to max length."""
    return text if len(text) <= max_len else text[:max_len]
