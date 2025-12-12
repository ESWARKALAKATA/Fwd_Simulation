"""
Run this script to index your GitHub repository into the vector database.

Steps:
1. Ensure .env has GITHUB_TOKEN, GITHUB_TARGET_REPO, and GEMINI_API_KEY
2. Run: python run_indexer.py [--full]
3. Wait for completion (incremental: seconds, full: 2-5 minutes)
4. Verify: SELECT count(*) FROM code_chunks;

This script (SMART MODE with incremental updates):
- Auto-detects changes since last index (tracks Git commit SHA)
- Only re-processes changed files (saves time & API quota)
- Falls back to full index if never indexed before
- Fetches Python files from the target GitHub repo
- Parses each file using Python AST to extract functions/classes
- Generates embeddings using Gemini (gemini-embedding-001)
- Stores chunks + embeddings in pgvector table

Options:
  --full    Force full re-index (ignore incremental)
"""
import asyncio
import sys
from app.vector.indexer_smart import index_github_repo_smart

async def main():
    # Check for --full flag
    force_full = "--full" in sys.argv
    
    print("="*80)
    print("GITHUB REPOSITORY INDEXER (Smart Mode)")
    print("="*80)
    print()
    if force_full:
        print("Mode: FULL INDEX (--full flag)")
        print()
    else:
        print("Mode: SMART (incremental if possible, full if needed)")
        print()
    print("This will:")
    print("  1. Check if repository changed since last index")
    print("  2. Fetch only changed Python files (or all if first time)")
    print("  3. Parse with AST (functions/classes)")
    print("  4. Generate embeddings with Gemini")
    print("  5. Store in pgvector table 'code_chunks'")
    print("  6. Track commit SHA for next incremental update")
    print()
    
    try:
        stats = await index_github_repo_smart(force_full=force_full)
        print()
        print("="*80)
        print("✓ INDEXING COMPLETE")
        print("="*80)
        print()
        print(f"Summary:")
        print(f"  Mode: {stats['mode'].upper()}")
        print(f"  Files Processed: {stats['files_processed']}")
        print(f"  Chunks Indexed: {stats['chunks_indexed']}")
        if 'total_files' in stats:
            print(f"  Total in DB: {stats['total_files']} files, {stats['total_chunks']} chunks")
        if 'commit_sha' in stats and stats['commit_sha'] != 'unknown':
            print(f"  Commit: {stats['commit_sha'][:7]}")
        print()
        print("Next steps:")
        print("  1. Start API: uvicorn app.main:app --reload")
        print("  2. Test query: POST /query {\"query\": \"Explain decision logic\"}")
        print("  3. Check logs for hybrid retrieval (github_search + vector)")
        print()
        if stats['mode'] == 'incremental':
            print("Tip: Run again to see instant 'up-to-date' detection!")
        if stats['mode'] == 'skip':
            print("Repository already up-to-date. No indexing needed.")
    except Exception as e:
        print()
        print("="*80)
        print("✗ INDEXING FAILED")
        print("="*80)
        print(f"Error: {e}")
        print()
        print("Common issues:")
        print("  - Missing GITHUB_TOKEN in .env")
        print("  - Missing GEMINI_API_KEY in .env")
        print("  - Invalid GITHUB_TARGET_REPO format")
        print("  - Postgres connection failure")
        print()
        print("To force full re-index: python run_indexer.py --full")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
