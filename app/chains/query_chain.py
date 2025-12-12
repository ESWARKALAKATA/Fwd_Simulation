from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langchain_core.runnables import RunnablePassthrough
from pydantic import BaseModel, Field
from typing import List, Optional
from app.llm.factory import get_llm

# --- Extraction Chain ---
class ExtractionResult(BaseModel):
    intent: str = Field(description="One of: simulate_decision, explain_rule, check_limit, action_justification, general_query")
    customer_names: List[str] = Field(description="List of customer names found in the query")
    source_systems: List[str] = Field(description="List of source systems (SRC1, SRC2, SRCX, etc.)")
    rule_codes: List[str] = Field(description="List of rule codes (R001, R002, R003, etc.)")
    amount: Optional[float] = Field(description="Numeric amount if mentioned")
    currency: Optional[str] = Field(description="Currency code if mentioned (USD, EUR, etc.)")
    schema_code: Optional[str] = Field(description="Schema code if mentioned (DUMMYX, DUMMYA, etc.)")
    input_id: Optional[int] = Field(description="Engine input ID if mentioned")
    needs_explanation: bool = Field(description="True if user asks why/explain/justify")

extraction_prompt = ChatPromptTemplate.from_template("""Extract structured information from the user query for a decisioning engine system.

The system evaluates transactions/requests through rules, scoring, and actions.
Classify the user intent and extract relevant entities.

Intent types:
- simulate_decision: User wants to run a hypothetical decision
- explain_rule: User asks about specific rule logic or why a rule triggered
- check_limit: User asks about source system limits
- action_justification: User asks why a specific action was taken
- general_query: Other questions about the system

Extract:
- customer_names: Full names of people/entities
- source_systems: System codes like SRC1, SRC2, SRCX
- rule_codes: Rule identifiers like R001, R002, R003
- amount: Numeric value if mentioned
- currency: Currency if mentioned (default USD)
- schema_code: Schema codes like DUMMYX, DUMMYA
- input_id: Numeric ID if user references a specific input
- needs_explanation: True if query contains why/explain/justify/reason

User Query: {query}

Return valid JSON matching the schema.
""")

def get_extraction_chain(model_id: str):
    llm = get_llm(model_id)
    parser = JsonOutputParser(pydantic_object=ExtractionResult)
    
    chain = (
        extraction_prompt 
        | llm 
        | parser
    )
    return chain

# --- Summary Chain ---
summary_prompt = ChatPromptTemplate.from_template("""You are an AI assistant for a decisioning engine system.
The system evaluates requests through rules, scoring calculations, and action derivations.

User Query: {query}

---
Logic Code Snippets (from repository):
{code_context}
---

---
Database Context (Live Data):
{db_context}
---

Provide a clear, detailed answer that:
1. Directly addresses the user's question
2. References specific logic from code snippets when relevant
3. Cites database records to support the explanation
4. Explains decision flow if asked about why/how
5. Uses technical terminology appropriately (rule codes, scores, actions)

Be concise but thorough.
""")

def get_query_chain(model_id: str):
    llm = get_llm(model_id)
    
    chain = (
        summary_prompt 
        | llm 
        | StrOutputParser()
    )
    
    return chain


def get_streaming_query_chain(model_id: str):
    """Return a chain configured for streaming responses."""
    llm = get_llm(model_id)
    
    chain = (
        summary_prompt 
        | llm 
        | StrOutputParser()
    )
    
    return chain
