# Decision Engine RAG System

A FastAPI service that combines code retrieval (hybrid lexical + semantic search) with LLM reasoning to answer queries about decision engine logic. Features intelligent incremental indexing, multi-provider LLM support, and real-time database integration.

## Features

- **Hybrid Code Retrieval**: GitHub Code Search (lexical) + pgvector semantic search
- **Incremental Indexing**: Git-based change detection, only re-processes modified files
- **Multi-LLM Support**: OpenRouter, Gemini 2.0, OpenAI, Ollama (local)
- **Entity Extraction**: Automatic detection of customer names, rule codes, amounts
- **Database Integration**: Real-time PostgreSQL queries with SQLAlchemy ORM
- **AST-Based Chunking**: Intelligent code parsing at function/class boundaries
- **Production Logging**: Rotating file logs with query analytics and performance tracking

## Quick Start

### 1. Create Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv myenv
.\myenv\Scripts\Activate.ps1
```

**Linux/macOS:**
```bash
python3 -m venv myenv
source myenv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy the example environment file and fill in your API keys:

```bash
# Copy example file
cp .env.example .env

# Edit .env with your favorite text editor
# Windows: notepad .env
# Linux/macOS: nano .env
```

**Required variables:**
- `GEMINI_API_KEY` - For embeddings and chat (get free key at [Google AI Studio](https://makersuite.google.com/app/apikey))
- `DATABASE_URL` - PostgreSQL connection string with pgvector (e.g., Neon serverless)
- `GITHUB_TOKEN` - Personal access token from [GitHub Settings](https://github.com/settings/tokens)
- `GITHUB_TARGET_REPO` - Full GitHub URL of repository to index

See `.env.example` for complete configuration options and documentation.

### 4. Index Repository

**First-time indexing (full):**
```bash
python run_indexer.py
```

**Force full re-index:**
```bash
python run_indexer.py --full
```

**Expected output:**
- First run: ~2-5 minutes (indexes all Python files)
- Subsequent runs: <1 second (auto-detects no changes)
- Incremental: 5-15 seconds (only changed files)

### 5. Start API Server

```bash
uvicorn app.main:app --reload
```

API available at: `http://localhost:8000`  
Interactive docs: `http://localhost:8000/docs`

## API Endpoints

### 1. Health Check
**`GET /health`**

Check if the service is running.

**Response:**
```json
{
  "status": "ok"
}
```

---

### 2. List Available Models
**`GET /models`**

Returns all configured LLM models.

**Response:**
```json
[
  {
    "id": "openrouter:default",
    "provider": "openrouter",
    "label": "OpenRouter Default (Cheap)",
    "default_usage": "general"
  },
  {
    "id": "gemini:gemini-2.0-flash-exp",
    "provider": "gemini",
    "label": "Gemini 2.0 Flash (Experimental)",
    "default_usage": "general"
  },
  {
    "id": "openai:gpt-4o-mini",
    "provider": "openai",
    "label": "OpenAI GPT-4o mini (cheap default)",
    "default_usage": "general"
  }
]
```

---

### 3. Query Engine (Main Endpoint)
**`POST /query`**

Retrieves relevant code and database context, then generates an answer using LLM.

**Request Body:**
```json
{
  "query": "Check if Vladimir Petrov's 50,000 USD transfer should be blocked",
  "model_id": "openrouter:default",
  "threshold": 0.7
}
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | ✅ Yes | - | Natural language question or command |
| `model_id` | string | ❌ No | `openrouter:default` | LLM model ID from `/models` |
| `threshold` | float | ❌ No | `null` | Reserved for future similarity filtering |

**Response:**
```json
{
  "answer": "Vladimir Petrov's transfer should be DECLINED. The customer has a risk score of 85 and is flagged as PEP (Politically Exposed Person). Historical records show a previous transaction from SRC1 for 50,000 USD that triggered rules R002 and R003, resulting in a DECLINE action with combined score 560...",
  "reasoning": {
    "code_snippets_count": 3,
    "db_context_summary": "Customer Found: Vladimir Petrov (Risk Score: 85, PEP: True)...",
    "extracted_entities": {
      "intent": "simulate_decision",
      "customer_names": ["Vladimir Petrov"],
      "amount": 50000,
      "source_systems": [],
      "rule_codes": []
    }
  },
  "model_id": "openrouter:default"
}
```

**Query Flow:**

1. **Repository Search (Hybrid)**
   - Lexical: GitHub Code Search API (exact keyword matching)
   - Semantic: pgvector similarity search (768-dim embeddings)
   - Result: Top 3-6 code snippets

2. **Entity Extraction (LLM)**
   - Parses query to extract: customer names, rule codes, amounts, source systems
   - Determines intent: `simulate_decision`, `explain_rule`, `check_limit`, etc.

3. **Database Queries (Conditional)**
   - Runs only if entities extracted
   - Queries: `customers`, `engine_inputs`, `rules`, `source_limits`
   - Returns historical decisions, risk scores, PEP status

4. **LLM Reasoning**
   - Combines code context + database context
   - Generates answer with citations and explanations

**Example Queries:**

```bash
# Simulate a decision
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Simulate a decision for Alice Johnson sending 3000 USD via SRCX"
  }'

# Explain a rule
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Why was rule R002 triggered for the last transaction?",
    "model_id": "gemini:gemini-2.0-flash-exp"
  }'

# Check limits
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the source limits for SRC1?"
  }'
```

## Logging & Monitoring

### Log Files

The system uses rotating file logs (10MB max, 5 backups):

```
logs/
  ├── app.log          # General application logs
  ├── query.log        # Query analytics & performance metrics
  └── indexer.log      # Indexing operations
```

### View Logs

```powershell
# View recent queries
Get-Content logs\query.log -Tail 20

# Monitor in real-time
Get-Content logs\query.log -Wait

# Find errors
Select-String "ERROR" logs\app.log

# Calculate average response time
Select-String "TIME_MS=" logs\query.log | ForEach-Object { 
    if ($_ -match "TIME_MS=(\d+\.\d+)") { [double]$matches[1] }
} | Measure-Object -Average
```

### Query Analytics Format

```
2025-11-24 21:58:37 | QUERY=user query | MODEL=model_id | CODE_SNIPPETS=5 | DB_ENTITIES=3 | TIME_MS=234.50 | SUCCESS=True
```

**Tracked metrics:**
- Query text and timestamp
- Model used
- Code snippets found
- Database entities retrieved
- Response time (milliseconds)
- Success/failure status
- Error messages (if failed)

For complete logging documentation, see [LOGGING.md](LOGGING.md) and [LOGGING_QUICK_REF.md](LOGGING_QUICK_REF.md).

## System Architecture

### Hybrid Retrieval Strategy

The system uses two complementary search methods:

1. **GitHub Code Search (Lexical)**
   - API: GitHub REST API `/search/code`
   - Matching: Exact keyword matching in code
   - Limitation: Natural language queries return 0 results (expected)
   - Best for: Specific identifiers, function names, constants

2. **pgvector Semantic Search**
   - Storage: PostgreSQL with pgvector extension
   - Model: `gemini-embedding-001` (768 dimensions)
   - Matching: Cosine similarity between query and code embeddings
   - Best for: Conceptual understanding, natural language queries

**Merge Strategy:**
- Combine results from both sources
- Deduplicate by file path
- Keep top 3-6 most relevant snippets
- Tag each snippet with source (`lexical` or `vector`)

### Incremental Indexing

**Three Operating Modes:**

| Mode | Trigger | Duration | API Calls | Description |
|------|---------|----------|-----------|-------------|
| **SKIP** | No changes detected | <1 sec | 0 | Instant detection via commit SHA comparison |
| **INCREMENTAL** | Some files changed | 5-15 sec | ~1-5 per file | Only processes modified/added files |
| **FULL** | First run or `--full` flag | 2-5 min | ~15 per file | Processes all Python files |

**Change Detection:**
- Tracks Git commit SHA in `indexer_metadata` table
- Compares with current HEAD via GitHub API
- Uses GitHub Compare API to get changed files list
- Deletes chunks for removed files

**Performance:**
- 150x faster for unchanged repos (3 min → <1 sec)
- Saves API quota (0 Gemini calls if no changes)
- Enables frequent indexing (hourly cron jobs)

### Database Schema

**Vector Storage:**
```sql
CREATE TABLE code_chunks (
    id SERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    path TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Indexing Metadata:**
```sql
CREATE TABLE indexer_metadata (
    repo TEXT PRIMARY KEY,
    last_commit_sha TEXT NOT NULL,
    last_indexed_at TIMESTAMPTZ,
    total_files INTEGER,
    total_chunks INTEGER
);
```

**Application Data (Example):**
```sql
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name TEXT,
    risk_score INTEGER,
    is_pep BOOLEAN,
    status TEXT
);

CREATE TABLE engine_inputs (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER,
    source TEXT,
    amount FLOAT,
    triggered_rules TEXT,
    decision TEXT,
    action TEXT
);
```

### Model Configuration

Edit `app/llm/registry.py` to add/remove models:

```python
# Example: Add custom Gemini model
self.models.append({
    "id": "gemini:gemini-pro",
    "provider": "gemini",
    "label": "Gemini Pro",
    "default_usage": "complex_reasoning"
})
```

## Troubleshooting


### Query Issues

**Problem:** Lexical search returns 0 results
```
Expected behavior: Natural language queries don't match code keywords
Vector search handles semantic understanding
Example: "transfer blocked" won't match code, but vectors will find "block_transaction()"
```

**Problem:** No database results
```
Check if entities were extracted:
1. Look for [STEP 4] ENTITY EXTRACTION in logs
2. Verify customer names/rule codes in query
3. Confirm database has matching records
```


## Development

### Project Structure

```
Fwd_Simulation/
├── app/
│   ├── api/
│   │   └── routes.py          # FastAPI endpoints
│   ├── chains/
│   │   └── query_chain.py     # LangChain prompts and chains
│   ├── db/
│   │   ├── models.py          # SQLAlchemy ORM models
│   │   ├── repositories.py    # Database query functions
│   │   └── session.py         # DB connection management
│   ├── github/
│   │   └── retriever.py       # Hybrid retrieval logic
│   ├── llm/
│   │   ├── embeddings.py      # Gemini embedding generation
│   │   ├── factory.py         # LLM provider factory
│   │   └── registry.py        # Model registration
│   ├── retrievers/
│   │   └── local_retriever.py # Local fallback retriever
│   ├── vector/
│   │   ├── incremental.py     # Change detection helpers
│   │   ├── indexer_smart.py   # Smart indexer (main)
│   │   └── indexer_v2.py      # AST chunking logic
│   ├── config.py              # Settings and environment
│   └── main.py                # FastAPI app initialization
├── run_indexer.py             # Indexing CLI script
├── requirements.txt           # Python dependencies
├── .env                       # Environment variables (create this)
└── README.md                  # This file
```

### Adding a New LLM Provider

1. **Register in `app/llm/registry.py`:**
```python
if settings.CUSTOM_API_KEY:
    self.models.append({
        "id": "custom:model-name",
        "provider": "custom",
        "label": "Custom Model Name",
        "default_usage": "general"
    })
```

2. **Add factory method in `app/llm/factory.py`:**
```python
elif provider == "custom":
    model_name = model_info["id"].split(":", 1)[1]
    return CustomChatModel(
        api_key=settings.CUSTOM_API_KEY,
        model=model_name
    )
```

3. **Update config in `app/config.py`:**
```python
CUSTOM_API_KEY: Optional[str] = None
```

### Testing

```bash
# Test indexing
python run_indexer.py

# Test API health
curl http://localhost:8000/health

# Test model listing
curl http://localhost:8000/models

# Test query with logging
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Test query"}' | jq
```

## Performance

- **Indexing Speed:**
  - First run: 2-5 minutes (15 files, ~30 chunks)
  - Incremental: 5-15 seconds (1-3 changed files)
  - Skip: <1 second (no changes)

- **Query Latency:**
  - Vector search: ~200-500ms (pgvector)
  - Entity extraction: ~1-2s (LLM call)
  - Database queries: ~50-100ms (PostgreSQL)
  - Final reasoning: ~2-5s (LLM generation)
  - **Total:** ~4-8 seconds per query

- **API Quotas:**
  - Gemini embeddings: 1,500 requests/day (free tier)
  - OpenRouter: Pay-as-you-go (DeepSeek: $0.14/1M tokens)
  - GitHub API: 5,000 requests/hour (authenticated)


## Support

For issues or questions:
1. Check logs: `logs/app.log`, `logs/query.log` (see [LOGGING.md](LOGGING.md))
2. Review documentation: `INCREMENTAL_INDEXING.md`, `LOGGING.md`, `LOGGING_QUICK_REF.md`
3. Verify environment: Ensure all required API keys in `.env`
4. Test logging: `python test_logging.py`
