"""Smart indexer with automatic incremental/full mode selection.

This module provides index_github_repo_smart() which:
1. Checks if repository changed since last index
2. If changed: only re-indexes modified files (incremental)
3. If never indexed: does full index (calls indexer_v2)
4. Preserves all existing functionality from indexer_v2.py
"""
from __future__ import annotations
import ast
import base64
import httpx
from typing import List, Tuple, Optional
from sqlalchemy import text
from app.config import settings
from app.llm.embeddings import get_embedding
from app.db.session import AsyncSessionLocal
from app.vector.incremental import (
    ensure_metadata_table,
    get_incremental_file_list,
    delete_chunks_for_files,
    update_indexed_commit,
    get_file_count_stats
)
# Import chunking functions from existing indexer
from app.vector.indexer_v2 import (
    _chunk_code_ast,
    _is_top_level,
    _chunk_code_regex,
    _slice_large,
    _truncate
)


async def index_github_repo_smart(
    repo: str | None = None,
    branch: str = "HEAD",
    file_limit: int = 150,
    force_full: bool = False
) -> dict:
    """Smart indexer that automatically chooses incremental vs full indexing.
    
    Args:
        repo: Repository in format "owner/name" (uses config if None)
        branch: Branch to index (default: HEAD/main)
        file_limit: Max files to process (safety limit)
        force_full: If True, always do full re-index (ignore incremental)
    
    Returns:
        Statistics dict with processed counts and mode used
    """
    repo = repo or settings.github_repo_name
    
    # Validation
    if not settings.GITHUB_TOKEN:
        raise ValueError("[Indexer] GITHUB_TOKEN required in .env")
    if not settings.GEMINI_API_KEY and settings.EMBEDDING_PROVIDER == "gemini":
        raise ValueError("[Indexer] GEMINI_API_KEY required for embedding generation")
    
    print(f"[Indexer] Target: {repo}")
    print(f"[Indexer] Embedding: {settings.EMBEDDING_PROVIDER}/{settings.EMBEDDING_MODEL} ({settings.EMBEDDING_DIM}D)")
    
    # Ensure metadata table exists
    await ensure_metadata_table()
    
    # Check if incremental indexing is possible
    if not force_full:
        files_to_index, files_to_delete, current_sha = await get_incremental_file_list(repo, branch)
        
        # Handle deleted files
        if files_to_delete:
            await delete_chunks_for_files(repo, files_to_delete)
        
        # If no files to index, we're done
        if files_to_index is not None and len(files_to_index) == 0:
            file_count, chunk_count = await get_file_count_stats(repo)
            print(f"[Indexer] ✓ Repository up-to-date ({file_count} files, {chunk_count} chunks)")
            return {
                "mode": "skip",
                "files_processed": 0,
                "chunks_indexed": 0,
                "files_deleted": len(files_to_delete),
                "commit_sha": current_sha
            }
        
        # If files_to_index is a list (not None), do incremental
        if files_to_index is not None:
            print(f"[Indexer] Mode: INCREMENTAL ({len(files_to_index)} files changed)")
            print()
            return await _index_specific_files(
                repo, branch, files_to_index, current_sha, file_limit
            )
    
    # Fall back to full indexing
    print(f"[Indexer] Mode: FULL (indexing all files)")
    if force_full:
        print(f"[Indexer] Reason: force_full=True")
    print()
    return await _index_all_files(repo, branch, file_limit)


async def _index_specific_files(
    repo: str,
    branch: str,
    file_paths: List[str],
    commit_sha: str,
    file_limit: int
) -> dict:
    """Index only specific files (incremental mode)."""
    owner, name = repo.split("/", 1)
    chunks_to_insert: List[Tuple[str, str, str, str]] = []
    
    async with httpx.AsyncClient(timeout=90) as client:
        headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"}
        
        # Process only changed files
        for idx, path in enumerate(file_paths[:file_limit], 1):
            print(f"[{idx}/{len(file_paths)}] Processing {path}...", end=" ")
            contents_url = f"https://api.github.com/repos/{owner}/{name}/contents/{path}"
            
            try:
                c_resp = await client.get(contents_url, headers=headers)
                if c_resp.status_code != 200:
                    print(f"✗ (fetch error {c_resp.status_code})")
                    continue
                
                c_data = c_resp.json()
                encoded = c_data.get("content")
                if not encoded:
                    print("✗ (no content)")
                    continue
                
                raw = base64.b64decode(encoded).decode("utf-8", errors="ignore")
                
                # Parse with AST (uses existing function from indexer_v2)
                chunks = _chunk_code_ast(raw, path)
                if not chunks:
                    print("✗ (no chunks)")
                    continue
                
                # Generate embeddings for each chunk
                for chunk_content in chunks:
                    embedding = await get_embedding(chunk_content)
                    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
                    
                    if len(embedding) != settings.EMBEDDING_DIM:
                        print(f"⚠ embedding dim={len(embedding)}, expected {settings.EMBEDDING_DIM}")
                    
                    chunks_to_insert.append((repo, path, chunk_content, embedding_str))
                
                print(f"✓ ({len(chunks)} chunks)")
            
            except Exception as e:
                print(f"✗ (error: {e})")
                continue
    
    # Delete old chunks for these files before inserting new ones
    print()
    print(f"[Indexer] Removing old chunks for {len(file_paths)} files...")
    await delete_chunks_for_files(repo, set(file_paths))
    
    # Insert new chunks
    print(f"[Indexer] Inserting {len(chunks_to_insert)} new chunks...")
    async with AsyncSessionLocal() as session:
        for repo_val, path_val, content_val, embedding_str_val in chunks_to_insert:
            await session.execute(
                text("""
                    INSERT INTO code_chunks (repo, path, content, embedding) 
                    VALUES (:repo, :path, :content, :embedding)
                """),
                {"repo": repo_val, "path": path_val, "content": content_val, "embedding": embedding_str_val}
            )
        await session.commit()
    
    # Update metadata with new commit SHA
    file_count, chunk_count = await get_file_count_stats(repo)
    await update_indexed_commit(repo, commit_sha, file_count, chunk_count)
    
    print(f"[Indexer] ✓ Incremental index complete: {len(file_paths)} files, {len(chunks_to_insert)} chunks")
    print(f"[Indexer] Total in database: {file_count} files, {chunk_count} chunks")
    
    return {
        "mode": "incremental",
        "files_processed": len(file_paths),
        "chunks_indexed": len(chunks_to_insert),
        "total_files": file_count,
        "total_chunks": chunk_count,
        "commit_sha": commit_sha
    }


async def _index_all_files(repo: str, branch: str, file_limit: int) -> dict:
    """Index all files in repository (full mode).
    
    This is similar to indexer_v2.py but also updates metadata tracking.
    """
    owner, name = repo.split("/", 1)
    chunks_to_insert: List[Tuple[str, str, str, str]] = []
    
    # Fetch file tree from GitHub
    async with httpx.AsyncClient(timeout=90) as client:
        headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"}
        tree_url = f"https://api.github.com/repos/{owner}/{name}/git/trees/{branch}?recursive=1"
        
        print(f"[Indexer] Fetching file tree from GitHub...")
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
        print(f"[Indexer] Found {len(py_paths)} Python files (limit: {file_limit})")
        print()
        
        # Process each file
        for idx, path in enumerate(py_paths, 1):
            print(f"[{idx}/{len(py_paths)}] Processing {path}...", end=" ")
            contents_url = f"https://api.github.com/repos/{owner}/{name}/contents/{path}"
            
            try:
                c_resp = await client.get(contents_url, headers=headers)
                if c_resp.status_code != 200:
                    print(f"✗ (fetch error {c_resp.status_code})")
                    continue
                
                c_data = c_resp.json()
                encoded = c_data.get("content")
                if not encoded:
                    print("✗ (no content)")
                    continue
                
                raw = base64.b64decode(encoded).decode("utf-8", errors="ignore")
                
                # Parse with AST
                chunks = _chunk_code_ast(raw, path)
                if not chunks:
                    print("✗ (no chunks)")
                    continue
                
                # Generate embeddings for each chunk
                for chunk_content in chunks:
                    embedding = await get_embedding(chunk_content)
                    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
                    
                    if len(embedding) != settings.EMBEDDING_DIM:
                        print(f"⚠ embedding dim={len(embedding)}, expected {settings.EMBEDDING_DIM}")
                    
                    chunks_to_insert.append((repo, path, chunk_content, embedding_str))
                
                print(f"✓ ({len(chunks)} chunks)")
            
            except Exception as e:
                print(f"✗ (error: {e})")
                continue
    
    # Verify/recreate table if dimension mismatch (preserve existing logic)
    async with AsyncSessionLocal() as dim_session:
        try:
            dim_result = await dim_session.execute(
                text("SELECT atttypmod FROM pg_attribute WHERE attrelid = 'code_chunks'::regclass AND attname='embedding'")
            )
            row = dim_result.fetchone()
            if row:
                existing_dim = row[0]
                if existing_dim != settings.EMBEDDING_DIM:
                    print(f"[Indexer] Dimension mismatch: existing={existing_dim} expected={settings.EMBEDDING_DIM}. Recreating table.")
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
            print(f"[Indexer] Warning: dimension check failed ({e})")
            await dim_session.rollback()
    
    # Bulk insert into database
    print()
    print(f"[Indexer] Inserting {len(chunks_to_insert)} chunks into pgvector table...")
    
    async with AsyncSessionLocal() as session:
        for repo_val, path_val, content_val, embedding_str_val in chunks_to_insert:
            await session.execute(
                text("""
                    INSERT INTO code_chunks (repo, path, content, embedding) 
                    VALUES (:repo, :path, :content, :embedding)
                """),
                {"repo": repo_val, "path": path_val, "content": content_val, "embedding": embedding_str_val}
            )
        await session.commit()
    
    # Get current commit SHA and update metadata
    try:
        from app.vector.incremental import fetch_current_commit_sha
        current_sha = await fetch_current_commit_sha(owner, name, branch)
        file_count, chunk_count = await get_file_count_stats(repo)
        await update_indexed_commit(repo, current_sha, file_count, chunk_count)
        print(f"[Indexer] ✓ Full index complete: {file_count} files, {chunk_count} chunks (commit: {current_sha[:7]})")
    except Exception as e:
        print(f"[Indexer] ✓ Full index complete: {len(py_paths)} files, {len(chunks_to_insert)} chunks")
        print(f"[Indexer] Warning: Could not track commit SHA ({e})")
        current_sha = "unknown"
    
    return {
        "mode": "full",
        "files_processed": len(py_paths),
        "chunks_indexed": len(chunks_to_insert),
        "total_files": len(py_paths),
        "total_chunks": len(chunks_to_insert),
        "commit_sha": current_sha
    }
