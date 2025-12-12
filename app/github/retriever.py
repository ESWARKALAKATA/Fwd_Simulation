"""GitHub-based retriever providing hybrid lexical + vector search."""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel
import httpx
import base64
from sqlalchemy import text
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.llm.embeddings import get_query_embedding
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CodeSnippet(BaseModel):
    path: str
    content: str
    url: str
    score: Optional[float] = None  # relevance score (combined)
    source: Optional[str] = None   # 'github_search' | 'vector' | 'hybrid'


class GitHubRepoRetriever:
    """Hybrid retriever for a remote GitHub repository."""

    def __init__(self, repo: Optional[str] = None, max_files: int = 8):
        self.repo = repo or settings.github_repo_name
        self.max_files = max_files
        self.token = settings.GITHUB_TOKEN

    async def retrieve_logic_snippets(self, user_query: str, intent: str = "general_query", top_k: int = 6) -> List[CodeSnippet]:
        lexical_snippets: List[CodeSnippet] = []
        if self.token:
            lexical_snippets = await self._github_code_search(user_query)
        else:
            logger.warning("No GitHub token available, skipping live search")

        vector_snippets: List[CodeSnippet] = []
        if settings.ENABLE_EMBED_INDEX and settings.HYBRID_RETRIEVAL:
            try:
                vector_snippets = await self._vector_search(user_query, limit=top_k)
            except Exception as e:
                logger.error(f"Vector search failed: {e}")

        merged = self._merge_results(lexical_snippets, vector_snippets)
        merged.sort(key=lambda c: c.score or 0, reverse=True)
        return merged[:top_k]

    async def _github_code_search(self, query: str) -> List[CodeSnippet]:
        keywords = [w for w in query.split() if len(w) > 3 and w.lower() not in {"sending", "simulate", "decision", "with", "from"}]
        search_terms = " ".join(keywords[:5])
        q = f"{search_terms} repo:{self.repo} language:Python"
        url = "https://api.github.com/search/code"
        params = {"q": q, "per_page": str(self.max_files)}
        headers = {"Accept": "application/vnd.github.text-match+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        results: List[CodeSnippet] = []
        async with httpx.AsyncClient(timeout=40) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                logger.error(f"GitHub code search error {resp.status_code}: {resp.text[:120]}")
                return results
            data = resp.json()
            total_count = data.get("total_count", 0)
            logger.info(f"GitHub lexical search: {total_count} files found, fetching top {self.max_files}")
            for item in data.get("items", [])[: self.max_files]:
                file_path = item.get("path")
                raw_url = item.get("url")  # contents API URL
                content = await self._fetch_raw_content(client, raw_url)
                if not content:
                    continue
                results.append(
                    CodeSnippet(
                        path=file_path,
                        content=content[:2000],
                        url=f"https://github.com/{self.repo}/blob/HEAD/{file_path}",
                        score=0.6,  # base lexical score
                        source="github_search",
                    )
                )
        return results

    async def _fetch_raw_content(self, client: httpx.AsyncClient, contents_api_url: str) -> Optional[str]:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        r = await client.get(contents_api_url, headers=headers)
        if r.status_code != 200:
            return None
        data = r.json()
        encoded = data.get("content")
        if not encoded:
            return None
        try:
            return base64.b64decode(encoded).decode("utf-8", errors="ignore")
        except Exception:
            return None

    async def _vector_search(self, query: str, limit: int = 6) -> List[CodeSnippet]:
        """Execute semantic search using pgvector embeddings.
        
        Expands query with code-relevant context for better matching.
        Checks dimension compatibility before executing search.
        Returns top-k most similar code chunks based on cosine similarity.
        """
        # Expand query with code-relevant context for better semantic matching
        expanded_query = f"""Python code that handles: {query}
        Relevant logic: decision rules, scoring, limits, validation, finalization
        """
        embedding = await get_query_embedding(expanded_query)
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
        
        # Check existing embedding vector dimension to avoid DataError (separate session)
        try:
            async with AsyncSessionLocal() as dim_session:
                dim_row = await dim_session.execute(text("SELECT atttypmod FROM pg_attribute WHERE attrelid = 'code_chunks'::regclass AND attname='embedding'"))
                dim_fetch = dim_row.fetchone()
                if dim_fetch:
                    existing_dim = dim_fetch[0]  # pgvector stores dimension directly
                    if existing_dim != settings.EMBEDDING_DIM:
                        logger.warning(f"Vector dimension mismatch: table={existing_dim}, config={settings.EMBEDDING_DIM}. Re-indexing required.")
                        return []
        except Exception as e:
            # Dimension check is optional - if it fails, proceed with vector search anyway
            logger.debug(f"Dimension check skipped: {e}")
        
        # Execute vector search with fresh session
        try:
            async with AsyncSessionLocal() as session:
                # Build SQL with inlined embedding cast to avoid asyncpg ':' cast syntax issue
                safe_embed = embedding_str.replace("'", "")  # embedding_str has only digits, commas, minus signs
                sql = text(
                    f"""
                    SELECT path, content, 1 - (embedding <=> '{safe_embed}'::vector) AS score
                    FROM code_chunks
                    WHERE repo = :repo
                    ORDER BY embedding <=> '{safe_embed}'::vector ASC
                    LIMIT :limit
                    """
                )
                rows = (await session.execute(sql, {"repo": self.repo, "limit": limit})).fetchall()
                if not rows:
                    logger.warning(f"Vector search: 0 chunks found for repo={self.repo}")
                else:
                    logger.info(f"Vector search: {len(rows)} chunks found")
                return [
                    CodeSnippet(
                        path=row[0],
                        content=row[1][:2000],
                        url=f"https://github.com/{self.repo}/blob/HEAD/{row[0]}",
                        score=float(row[2]),
                        source="vector",
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Vector search execution failed: {e}")
            return []

    def _merge_results(self, lexical: List[CodeSnippet], vector: List[CodeSnippet]) -> List[CodeSnippet]:
        by_path: dict[str, CodeSnippet] = {}
        for item in lexical + vector:
            if item.path not in by_path:
                by_path[item.path] = item
            else:
                existing = by_path[item.path]
                existing.score = max(existing.score or 0, item.score or 0)
                if existing.source != item.source:
                    existing.source = "hybrid"
        return list(by_path.values())

