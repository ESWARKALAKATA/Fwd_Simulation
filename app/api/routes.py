from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
import time
import json
import asyncio

from app.db.session import get_db
from app.db.repositories import DataRepository
from app.llm.registry import registry
from app.github.retriever import GitHubRepoRetriever
from app.retrievers.local_retriever import LocalRepoRetriever
from app.chains.query_chain import get_query_chain, get_extraction_chain, get_streaming_query_chain
from app.config import settings
from app.utils.logger import get_logger, log_query_analytics

logger = get_logger(__name__)
router = APIRouter()

class QueryRequest(BaseModel):
    query: str
    threshold: Optional[float] = None
    model_id: Optional[str] = None
    stream: Optional[bool] = False  # Enable streaming mode

class QueryResponse(BaseModel):
    answer: str
    reasoning: Optional[Any] = None
    model_id: str

@router.get("/health")
async def health_check():
    return {"status": "ok"}

@router.get("/models")
async def list_models():
    return registry.list_models()

@router.post("/query", response_model=QueryResponse)
async def run_query(request: QueryRequest, db: AsyncSession = Depends(get_db)):
    start_time = time.time()
    logger.info(f"Query received: '{request.query[:80]}...'" if len(request.query) > 80 else f"Query received: '{request.query}'")
    
    # 1. Determine Model
    model_id = request.model_id
    if not model_id:
        # Pick first available or default to OpenRouter if available
        models = registry.list_models()
        if not models:
            raise HTTPException(status_code=500, detail="No LLM models configured.")
        openrouter_model = next((m for m in models if m["provider"] == "openrouter"), None)
        model_id = openrouter_model["id"] if openrouter_model else models[0]["id"]
    
    logger.info(f"Using model: {model_id}")

    # 2. Retrieve Logic (Hybrid Strategy)
    active_retriever = None
    snippets: List[Any] = []

    if settings.GITHUB_TOKEN:
        active_retriever = GitHubRepoRetriever()
        snippets = await active_retriever.retrieve_logic_snippets(request.query, intent="general_query")
    else:
        logger.warning("No GitHub token configured, using LocalRepoRetriever")
        active_retriever = LocalRepoRetriever()
        snippets = await active_retriever.retrieve_logic_snippets(request.query, intent="general_query")

    logger.info(f"Code retrieval: {len(snippets)} snippets found - Files: {[s.path for s in snippets]}")

    code_context = "\n\n".join([f"File: {s.path}\nContent:\n{s.content}" for s in snippets]) or "No relevant code found in repository."

    # 3. DB Interaction (Phase 1 with Intent-Based Extraction)
    repo = DataRepository(db)
    db_context_parts = []
    db_entities_found = 0
    
    try:
        # Extract entities to query DB (uses LLM to identify customer names, rule codes, etc.)
        extraction_chain = get_extraction_chain(model_id)
        extracted = await extraction_chain.ainvoke({"query": request.query})
        
        # Re-search repository with intent if needed
        intent = extracted.get('intent', 'general_query')
        if intent != 'general_query':
            # Re-run retrieval with specific intent for better results
            logger.info(f"Re-searching with intent: {intent}")
            snippets = await active_retriever.retrieve_logic_snippets(request.query, intent=intent)
            code_context = "\n\n".join([f"File: {s.path}\nContent:\n{s.content}" for s in snippets]) or "No relevant code found in repository."
        
        # Search Customers
        for name in extracted.get("customer_names", []):
            cust = await repo.get_customer_by_name(name)
            if cust:
                db_entities_found += 1
                result_msg = f"Customer Found: {cust.full_name} (Risk Score: {cust.risk_score}, PEP: {cust.pep_flag}, Status: {cust.status})"
                db_context_parts.append(result_msg)
                
                inputs = await repo.get_engine_inputs_by_customer(cust.id)
                if inputs:
                    for inp in inputs:
                        db_entities_found += 1
                        inp_msg = f"  Engine Input #{inp.id}: Source={inp.source_system}, Amount={inp.amount} {inp.currency}, Schema={inp.schema_code}, CardScore={inp.card_score}, ModelScore={inp.model_score}"
                        db_context_parts.append(inp_msg)
                        
                        triggers = await repo.get_rule_triggers_by_input(inp.id)
                        if triggers:
                            trigger_codes = [t.rule_code for t in triggers]
                            trigger_msg = f"    Triggered Rules: {', '.join(trigger_codes)}"
                            db_context_parts.append(trigger_msg)
                        
                        decision = await repo.get_decision_by_input(inp.id)
                        if decision:
                            dec_msg = f"    Decision: {decision.final_decision} (Action: {decision.action}, Combined Score: {decision.combined_score})"
                            db_context_parts.append(dec_msg)
            else:
                result_msg = f"Customer '{name}' not found in DB."
                db_context_parts.append(result_msg)

        # Search Source Limits
        for src in extracted.get("source_systems", []):
            limit = await repo.get_source_limit(src)
            if limit:
                db_entities_found += 1
                result_msg = f"Source Limit Found: {limit.source_system} = {limit.limit_amount}"
                db_context_parts.append(result_msg)
            else:
                result_msg = f"Source limit for '{src}' not found in DB."
                db_context_parts.append(result_msg)

        # Search by Rule Code
        for rule in extracted.get("rule_codes", []):
            matches = await repo.search_by_rule_code(rule)
            if matches:
                db_entities_found += len(matches)
                for match in matches:
                    rule_msg = f"  Rule {rule} triggered for Input #{match.input_id}"
                    db_context_parts.append(rule_msg)
            else:
                result_msg = f"No triggers found for rule '{rule}'."
                db_context_parts.append(result_msg)
        
        # If input_id is specified, fetch that specific input
        if extracted.get("input_id"):
            input_id = extracted["input_id"]
            engine_input = await repo.get_engine_input_by_id(input_id)
            if engine_input:
                db_entities_found += 1
                inp_msg = f"Engine Input #{engine_input.id}: Customer={engine_input.customer_id}, Source={engine_input.source_system}, Amount={engine_input.amount}"
                db_context_parts.append(inp_msg)
            else:
                db_context_parts.append(f"Input #{input_id} not found")
        
        logger.info(f"Database lookup: {db_entities_found} entities found")

    except Exception as e:
        logger.error(f"Entity extraction failed: {e}")
        # Fallback: just list all customers and limits
        customers = await repo.get_all_customers()
        limits = await repo.get_all_source_limits()
        db_context_parts.append(f"Found {len(customers)} customers and {len(limits)} source limits (Fallback).")

    db_context = "\n".join(db_context_parts)
    if not db_context:
        db_context = "No relevant data found in DB."
    
    # 4. Check if streaming is requested
    if request.stream:
        logger.info("Streaming mode enabled")
        return await handle_streaming_query(
            request=request,
            model_id=model_id,
            code_context=code_context,
            db_context=db_context,
            snippets=snippets,
            db_entities_found=db_entities_found,
            extracted=extracted if 'extracted' in locals() else {},
            start_time=start_time
        )
    
    # 5. Run Chain (Non-Streaming)
    logger.info("Non-streaming mode (standard JSON response)")
    try:
        chain = get_query_chain(model_id)
        answer = await chain.ainvoke({
            "query": request.query,
            "code_context": code_context,
            "db_context": db_context
        })
        
        response_time_ms = (time.time() - start_time) * 1000
        logger.info(f"Query completed successfully - Response time: {response_time_ms:.2f}ms")
        
        # Log query analytics
        log_query_analytics(
            query=request.query,
            model_id=model_id,
            code_snippets_count=len(snippets),
            db_entities_found=db_entities_found,
            response_time_ms=response_time_ms,
            success=True
        )
        
    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000
        logger.error(f"LLM execution failed after {response_time_ms:.2f}ms: {str(e)}")
        
        log_query_analytics(
            query=request.query,
            model_id=model_id,
            code_snippets_count=len(snippets),
            db_entities_found=db_entities_found,
            response_time_ms=response_time_ms,
            success=False,
            error=str(e)
        )
        
        raise HTTPException(status_code=500, detail=f"LLM execution failed: {str(e)}")
    
    return QueryResponse(
        answer=answer,
        reasoning={
            "code_snippets_count": len(snippets),
            "db_context_summary": db_context,
            "extracted_entities": extracted if 'extracted' in locals() else None
        },
        model_id=model_id
    )


async def handle_streaming_query(
    request: QueryRequest,
    model_id: str,
    code_context: str,
    db_context: str,
    snippets: List[Any],
    db_entities_found: int,
    extracted: dict,
    start_time: float
):
    """Handle streaming response using Server-Sent Events format."""
    
    async def event_generator():
        try:
            # Send initial metadata
            metadata = {
                "type": "metadata",
                "model_id": model_id,
                "code_snippets_count": len(snippets),
                "db_entities_found": db_entities_found,
                "extracted_entities": extracted
            }
            yield f"data: {json.dumps(metadata)}\n\n"
            
            # Get streaming chain
            chain = get_streaming_query_chain(model_id)
            
            # Stream the response
            chunk_count = 0
            async for chunk in chain.astream({
                "query": request.query,
                "code_context": code_context,
                "db_context": db_context
            }):
                chunk_count += 1
                chunk_data = {
                    "type": "content",
                    "content": chunk
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
                await asyncio.sleep(0)  # Allow other tasks to run
            
            # Send completion message
            response_time_ms = (time.time() - start_time) * 1000
            completion_data = {
                "type": "done",
                "response_time_ms": response_time_ms,
                "chunks_sent": chunk_count
            }
            yield f"data: {json.dumps(completion_data)}\n\n"
            
            logger.info(f"Streaming completed - Response time: {response_time_ms:.2f}ms, Chunks: {chunk_count}")
            
            # Log analytics
            log_query_analytics(
                query=request.query,
                model_id=model_id,
                code_snippets_count=len(snippets),
                db_entities_found=db_entities_found,
                response_time_ms=response_time_ms,
                success=True
            )
            
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            logger.error(f"Streaming failed after {response_time_ms:.2f}ms: {str(e)}")
            
            error_data = {
                "type": "error",
                "error": str(e)
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            
            log_query_analytics(
                query=request.query,
                model_id=model_id,
                code_snippets_count=len(snippets),
                db_entities_found=db_entities_found,
                response_time_ms=response_time_ms,
                success=False,
                error=str(e)
            )
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
