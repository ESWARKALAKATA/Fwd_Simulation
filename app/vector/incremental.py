"""Incremental indexing support with GitHub commit tracking."""
from __future__ import annotations
import httpx
from typing import List, Optional, Set
from sqlalchemy import text
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.utils.logger import get_indexer_logger

logger = get_indexer_logger()


async def ensure_metadata_table():
    """Create indexer_metadata table if it doesn't exist."""
    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS indexer_metadata (
                repo TEXT PRIMARY KEY,
                last_commit_sha TEXT NOT NULL,
                last_indexed_at TIMESTAMPTZ DEFAULT NOW(),
                total_files INTEGER DEFAULT 0,
                total_chunks INTEGER DEFAULT 0
            );
        """))
        await session.commit()


async def get_last_indexed_commit(repo: str) -> Optional[str]:
    """Get the last indexed commit SHA for a repository."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT last_commit_sha FROM indexer_metadata WHERE repo = :repo"),
            {"repo": repo}
        )
        row = result.fetchone()
        return row[0] if row else None


async def update_indexed_commit(repo: str, commit_sha: str, total_files: int, total_chunks: int):
    """Update the last indexed commit SHA and stats for a repository."""
    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            INSERT INTO indexer_metadata (repo, last_commit_sha, last_indexed_at, total_files, total_chunks)
            VALUES (:repo, :sha, NOW(), :files, :chunks)
            ON CONFLICT (repo) DO UPDATE 
            SET last_commit_sha = :sha, 
                last_indexed_at = NOW(),
                total_files = :files,
                total_chunks = :chunks
        """), {"repo": repo, "sha": commit_sha, "files": total_files, "chunks": total_chunks})
        await session.commit()


async def fetch_current_commit_sha(owner: str, name: str, branch: str = "HEAD") -> str:
    """Get the current commit SHA for a branch from GitHub."""
    # Handle HEAD by fetching default branch
    if branch == "HEAD":
        # Get default branch first
        repo_url = f"https://api.github.com/repos/{owner}/{name}"
        async with httpx.AsyncClient(timeout=30) as client:
            headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"}
            repo_resp = await client.get(repo_url, headers=headers)
            if repo_resp.status_code == 200:
                branch = repo_resp.json().get("default_branch", "main")
    
    url = f"https://api.github.com/repos/{owner}/{name}/git/refs/heads/{branch}"
    async with httpx.AsyncClient(timeout=30) as client:
        headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"}
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch commit SHA: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        return data["object"]["sha"]


async def fetch_changed_files(owner: str, name: str, base_sha: str, head_sha: str) -> tuple[Set[str], Set[str]]:
    """Get sets of added/modified and deleted Python files between commits.
    
    Returns:
        (changed_files, deleted_files) - both are sets of file paths
    """
    url = f"https://api.github.com/repos/{owner}/{name}/compare/{base_sha}...{head_sha}"
    async with httpx.AsyncClient(timeout=30) as client:
        headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"}
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to compare commits: {resp.status_code} {resp.text[:200]}")
        
        data = resp.json()
        changed_paths = set()
        deleted_paths = set()
        
        for file_data in data.get("files", []):
            path = file_data["filename"]
            if not path.endswith(".py"):
                continue
            
            status = file_data["status"]
            if status in ["added", "modified", "renamed"]:
                changed_paths.add(path)
                # Handle renames: remove old path
                if status == "renamed" and "previous_filename" in file_data:
                    deleted_paths.add(file_data["previous_filename"])
            elif status == "removed":
                deleted_paths.add(path)
        
        return changed_paths, deleted_paths


async def delete_chunks_for_files(repo: str, file_paths: Set[str]):
    """Delete all chunks for the given file paths."""
    if not file_paths:
        return
    
    async with AsyncSessionLocal() as session:
        for path in file_paths:
            await session.execute(
                text("DELETE FROM code_chunks WHERE repo = :repo AND path = :path"),
                {"repo": repo, "path": path}
            )
        await session.commit()
    
    logger.info(f"Deleted chunks for {len(file_paths)} removed/renamed files")


async def check_if_reindex_needed(repo: str, branch: str = "HEAD") -> tuple[bool, Optional[str], Optional[str]]:
    """Check if incremental re-indexing is needed.
    
    Returns:
        (needs_update, last_commit_sha, current_commit_sha)
        - needs_update: True if files changed since last index
        - last_commit_sha: Previously indexed commit (None if never indexed)
        - current_commit_sha: Current HEAD commit
    """
    owner, name = repo.split("/", 1)
    
    try:
        current_sha = await fetch_current_commit_sha(owner, name, branch)
        last_sha = await get_last_indexed_commit(repo)
        
        if last_sha is None:
            # Never indexed before
            return True, None, current_sha
        
        if last_sha == current_sha:
            # No changes since last index
            return False, last_sha, current_sha
        
        # Commits differ - check what changed
        return True, last_sha, current_sha
    
    except Exception as e:
        # On error, assume full re-index needed
        logger.warning(f"Commit check failed ({e}), will do full index")
        return True, None, None


async def get_incremental_file_list(repo: str, branch: str = "HEAD") -> tuple[Optional[List[str]], Set[str], str]:
    """Get list of files to re-index (None means full re-index needed).
    
    Returns:
        (files_to_index, files_to_delete, current_commit_sha)
        - files_to_index: List of changed file paths (None = index all files)
        - files_to_delete: Set of deleted file paths
        - current_commit_sha: Current commit SHA for tracking
    """
    owner, name = repo.split("/", 1)
    needs_update, last_sha, current_sha = await check_if_reindex_needed(repo, branch)
    
    if not needs_update:
        # No changes - return empty lists
        logger.info(f"Repository up-to-date (commit: {current_sha[:7]})")
        return [], set(), current_sha
    
    if last_sha is None or current_sha is None:
        # First time indexing or commit check failed - do full index
        logger.info("First-time indexing or commit tracking unavailable")
        return None, set(), current_sha or "unknown"
    
    # Get changed files
    try:
        changed_files, deleted_files = await fetch_changed_files(owner, name, last_sha, current_sha)
        
        if not changed_files and not deleted_files:
            logger.info(f"No Python files changed (commit: {last_sha[:7]} → {current_sha[:7]})")
            return [], set(), current_sha
        
        logger.info(f"Detected changes: {len(changed_files)} modified, {len(deleted_files)} deleted")
        logger.info(f"Commit: {last_sha[:7]} → {current_sha[:7]}")
        # On error comparing commits, fall back to full index
        return list(changed_files), deleted_files, current_sha
    
    except Exception as e:
        logger.warning(f"Failed to detect changes ({e}), doing full re-index")
        return None, set(), current_sha


async def get_file_count_stats(repo: str) -> tuple[int, int]:
    """Get current file and chunk counts for a repository."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT COUNT(DISTINCT path), COUNT(*) FROM code_chunks WHERE repo = :repo"),
            {"repo": repo}
        )
        row = result.fetchone()
        return (row[0] or 0, row[1] or 0)
