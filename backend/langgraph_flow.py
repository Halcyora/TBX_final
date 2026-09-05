"""
LangGraph Agentic Loop for Finance Assistant
State machine for query processing pipeline
"""

import json
import os
import logging
import asyncio
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime

import boto3
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from database import get_db
from prompts import (
    build_few_shot_prompt, build_cot_prompt, build_response_prompt,
    build_classification_prompt, CLASSIFICATION_PROMPT, SQL_VALIDATION_PROMPT,
    CLARIFICATION_PROMPT_TEMPLATE
)
from sql_validator import SQLValidator
from tools import QueryExecutor, AnomalyDetector, DataExporter, ContextManager

load_dotenv()
logger = logging.getLogger(__name__)

# ============================================================================
# LLM CLIENT
#
# Qwen 1.5B: Optimized for financial queries
# Prefers HuggingFace Inference API when HUGGINGFACE_API_KEY set
# Falls back to AWS Bedrock if needed
# Fully compliant with Problem Statement Section 7 hard constraint (<=20B params)
# ============================================================================

DEFAULT_MODEL_ALIAS = "qwen-1.5b"  # HuggingFace Qwen 1.5B - PS-compliant

# Bedrock model aliases for benchmarking
_MODEL_ALIAS_ENV_KEYS = {
    "qwen-1.5b": "QWEN_MODEL_ID",
    "amazon.nova-micro": "NOVA_MICRO_MODEL_ID",
    "llama3-1-8b": "LLAMA_8B_MODEL_ID",
    "mistral-7b": "MISTRAL_7B_MODEL_ID",
    "llama4-scout-17b": "LLAMA_SCOUT_17B_MODEL_ID",
}
_MODEL_ALIAS_DEFAULTS = {
    "qwen-1.5b": "qwen-1.5b",  # Uses HuggingFace when HUGGINGFACE_API_KEY set
    "amazon.nova-micro": "amazon.nova-micro-v1:0",
    "llama3-1-8b": "meta.llama3-1-8b-instruct-v1:0",
    "mistral-7b": "mistral.mistral-7b-instruct-v0:2",
    "llama4-scout-17b": "meta.llama4-scout-17b-instruct-v1:0",
}

_bedrock_client = None
_hf_client = None

HF_MODEL_ID = os.getenv("HF_MODEL_ID", "Qwen/Qwen2.5-Coder-1.5B-Instruct")
# This model is only served by the featherless-ai partner provider on HF's router
HF_PROVIDER = os.getenv("HF_PROVIDER", "featherless-ai")


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
    return _bedrock_client


def _get_hf_client() -> Optional[InferenceClient]:
    """Lazily build a Hugging Face Inference client if an API key is configured"""
    global _hf_client
    token = os.getenv("HUGGINGFACE_API_KEY")
    if not token:
        return None
    if _hf_client is None:
        _hf_client = InferenceClient(model=HF_MODEL_ID, token=token, provider=HF_PROVIDER)
    return _hf_client


def _call_hf(prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
    client = _get_hf_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = client.chat_completion(messages=messages, max_tokens=max_tokens, temperature=temperature)
    return response.choices[0].message.content


def _resolve_model_id(model_alias: str) -> str:
    alias = model_alias if model_alias in _MODEL_ALIAS_ENV_KEYS else "amazon.nova-micro"
    env_key = _MODEL_ALIAS_ENV_KEYS[alias]
    return os.getenv(env_key, _MODEL_ALIAS_DEFAULTS[alias])


def call_llm(prompt: str, model_alias: str = DEFAULT_MODEL_ALIAS, system: Optional[str] = None,
             max_tokens: int = 1024, temperature: float = 0.2) -> str:
    """Call the configured LLM and return its text response.

    Prefers the Hugging Face Inference API (Qwen2.5-Coder-1.5B-Instruct) when
    HUGGINGFACE_API_KEY is set, falling back to AWS Bedrock otherwise/on error.
    """
    if _get_hf_client() is not None:
        try:
            return _call_hf(prompt, system, max_tokens, temperature)
        except Exception as e:
            logger.warning(f"Hugging Face inference failed, falling back to Bedrock: {e}")

    model_id = _resolve_model_id(model_alias)
    client = _get_bedrock_client()

    kwargs: Dict[str, Any] = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if system:
        kwargs["system"] = [{"text": system}]

    response = client.converse(**kwargs)
    return response["output"]["message"]["content"][0]["text"]

# ============================================================================
# STATE DEFINITION
# ============================================================================
class FinanceAssistantState(BaseModel):
    """State for the LangGraph"""
    user_query: str
    conversation_history: List[Dict[str, Any]] = []
    
    # Parsing stage
    intent: Optional[str] = None
    entities: Dict[str, Any] = {}
    filters: Dict[str, Any] = {}
    confidence_score: float = 0.0
    needs_clarification: bool = False
    clarification_questions: List[str] = []
    
    # SQL generation stage
    sql_query: Optional[str] = None
    sql_valid: bool = False
    sql_errors: List[str] = []
    
    # Execution stage
    query_results: List[Dict[str, Any]] = []
    execution_error: Optional[str] = None
    
    # Anomaly detection stage
    anomalies: List[Dict[str, Any]] = []
    anomaly_summary: str = ""
    
    # Response stage
    final_answer: str = ""
    confidence_components: Dict[str, float] = {}
    composite_confidence: float = 0.0
    export_filename: Optional[str] = None
    grounding_info: Dict[str, Any] = {}
    
    # Meta
    model_used: str = "qwen-1.5b"
    processing_stages_completed: List[str] = []
    stage_details: Dict[str, str] = {}
    
    class Config:
        arbitrary_types_allowed = True


# ============================================================================
# NODE FUNCTIONS
# ============================================================================

async def classify_query_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    Parse user query to extract intent, entities, filters, confidence
    """
    logger.info(f"Classifying query: {state.user_query[:100]}")
    
    try:
        history_context = ContextManager.format_history_for_prompt(state.conversation_history)
        prompt = build_classification_prompt(state.user_query, history_context)

        response_text = await asyncio.to_thread(
            call_llm, prompt, model_alias=state.model_used, max_tokens=1024, temperature=0.1
        )
        
        # Try to extract JSON
        try:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                classification = json.loads(response_text[json_start:json_end])
            else:
                classification = json.loads(response_text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse classification JSON, using defaults")
            classification = {
                "intent": "unknown",
                "entities": {},
                "filters": {},
                "confidence_score": 0.5,
                "clarification_questions": []
            }
        
        state.intent = classification.get("intent", "unknown")
        state.entities = classification.get("entities", {})
        state.filters = classification.get("filters", {})
        state.confidence_score = float(classification.get("confidence_score", 0.5))
        state.clarification_questions = classification.get("clarification_questions", [])
        
        # Determine if clarification needed (low confidence)
        state.needs_clarification = state.confidence_score < 0.6
        
        state.processing_stages_completed.append("classification")
        entities_str = ", ".join([f"{k}={v}" for k, v in state.entities.items()]) if state.entities else "none"
        filters_str = ", ".join([f"{k}={v}" for k, v in state.filters.items()]) if state.filters else "none"
        state.stage_details["classification"] = (
            f"Intent: {state.intent} | Entities: {entities_str} | Filters: {filters_str} | Confidence: {state.confidence_score:.0%}"
        )
        logger.info(f"Classification complete: intent={state.intent}, confidence={state.confidence_score:.2f}")
        
    except Exception as e:
        logger.error(f"Classification node error: {e}")
        state.execution_error = str(e)
    
    return state


async def clarification_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    If confidence is low, generate clarification questions
    (In real implementation, would ask user via chat interface)
    """
    if not state.needs_clarification:
        return state
    
    logger.info("Requesting clarification")
    
    questions = state.clarification_questions or [
        "Could you specify the vendor, date range, or metric you're asking about?"
    ]
    clarifications = "\n".join([f"- {q}" for q in questions])
    
    # Surface the clarification to the user directly (this path skips response_formatting_node)
    state.final_answer = CLARIFICATION_PROMPT_TEMPLATE.format(
        question=state.user_query, clarification_questions=clarifications
    )
    state.grounding_info = {
        "reason": "clarification_requested",
        "confidence_score": state.confidence_score,
    }
    
    state.processing_stages_completed.append("clarification_requested")
    state.stage_details["clarification_requested"] = f"Asked {len(questions)} clarifying question(s)"
    return state


async def sql_generation_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    Generate SQL query using few-shot + chain-of-thought
    """
    logger.info(f"SQL generation node called: user_query={state.user_query[:50]}")
    
    if state.needs_clarification:
        logger.info("Skipping SQL generation due to clarification needed")
        return state
    
    try:
        logger.info("Calling LLM for chain-of-thought reasoning")
        history_context = ContextManager.format_history_for_prompt(state.conversation_history)

        # First, build CoT prompt
        cot_prompt = build_cot_prompt(state.user_query, history_context)
        
        # Get chain-of-thought reasoning
        cot_text = await asyncio.to_thread(
            call_llm, cot_prompt, model_alias=state.model_used, max_tokens=500, temperature=0.2
        )
        logger.debug(f"Chain-of-thought: {cot_text[:200]}")
        logger.info("CoT reasoning complete, now generating SQL with few-shot examples")
        
        # Now generate SQL with few-shot examples
        few_shot_prompt = build_few_shot_prompt(state.user_query, history_context)
        
        sql_text = (await asyncio.to_thread(
            call_llm, few_shot_prompt, model_alias=state.model_used, max_tokens=1024, temperature=0.1
        )).strip()
        
        # Clean up SQL (remove markdown formatting if present)
        if "```sql" in sql_text:
            sql_text = sql_text.split("```sql")[1].split("```")[0].strip()
        elif "```" in sql_text:
            sql_text = sql_text.split("```")[1].split("```")[0].strip()
        
        state.sql_query = sql_text
        state.processing_stages_completed.append("sql_generation")
        # Show full SQL or truncate if very long
        sql_preview = sql_text.strip()[:200] + "..." if len(sql_text.strip()) > 200 else sql_text.strip()
        state.stage_details["sql_generation"] = f"SQL Query:\n{sql_preview}"
        logger.info(f"SQL generated: {sql_text[:100]}...")
        
    except Exception as e:
        logger.error(f"SQL generation error: {e}")
        state.execution_error = f"SQL generation failed: {str(e)}"
    
    return state


async def sql_validation_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    Validate SQL with both static checks and LLM validation
    """
    if not state.sql_query or state.execution_error:
        return state
    
    logger.info("Validating SQL")
    
    try:
        # Static validation
        is_valid, validation_msg = SQLValidator.validate_query(state.sql_query)
        
        if not is_valid:
            state.sql_valid = False
            state.sql_errors.append(validation_msg)
            logger.warning(f"Static validation failed: {validation_msg}")
        else:
            # LLM-based semantic validation - the LLM may rewrite the query, so it must be
            # re-checked with the same static safety net before being trusted for execution
            corrected_sql = (await asyncio.to_thread(
                call_llm, SQL_VALIDATION_PROMPT.format(sql=state.sql_query),
                model_alias=state.model_used, max_tokens=1024, temperature=0.0
            )).strip()
            
            if "```sql" in corrected_sql:
                corrected_sql = corrected_sql.split("```sql")[1].split("```")[0].strip()
            elif "```" in corrected_sql:
                corrected_sql = corrected_sql.split("```")[1].split("```")[0].strip()
            
            revalidated, revalidation_msg = SQLValidator.validate_query(corrected_sql)
            if revalidated:
                state.sql_query = corrected_sql
                state.sql_valid = True
                state.processing_stages_completed.append("sql_validation")
                state.stage_details["sql_validation"] = "Passed static + LLM semantic checks (query refined)"
                logger.info("SQL validation passed (LLM-corrected query re-verified)")
            else:
                # LLM's "correction" failed the safety net - keep the original query,
                # which already passed static validation above
                logger.warning(
                    f"LLM-corrected SQL failed re-validation ({revalidation_msg}); "
                    f"keeping original validated query instead"
                )
                state.sql_valid = True
                state.processing_stages_completed.append("sql_validation")
                state.stage_details["sql_validation"] = "Passed static checks (kept original query)"
        
    except Exception as e:
        logger.error(f"SQL validation error: {e}")
        state.sql_errors.append(str(e))
    
    return state


async def query_execution_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    Execute validated SQL query
    """
    if not state.sql_valid or not state.sql_query:
        logger.info("Skipping execution due to validation failure")
        return state
    
    logger.info("Executing query")
    
    try:
        success, result = QueryExecutor.execute(state.sql_query)
        
        if success:
            state.query_results = result if isinstance(result, list) else [result]
            state.processing_stages_completed.append("query_execution")
            rows = len(state.query_results)
            cols = len(state.query_results[0]) if state.query_results and len(state.query_results) > 0 else 0
            state.stage_details["query_execution"] = f"Execution successful | {rows} row(s) × {cols} column(s)"
            logger.info(f"Query execution successful, {rows} rows returned with {cols} columns")
        else:
            state.execution_error = str(result)
            logger.error(f"Query execution failed: {result}")
        
    except Exception as e:
        logger.error(f"Query execution error: {e}")
        state.execution_error = str(e)
    
    return state


async def anomaly_detection_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    Detect anomalies in results using hybrid approach
    """
    if not state.query_results:
        return state
    
    logger.info("Detecting anomalies")
    
    try:
        detector = AnomalyDetector()
        anomaly_result = detector.detect_anomalies(state.query_results)
        
        # Flatten each anomaly's nested "row" into the top-level id/amount fields the
        # frontend (and CSV/response) expects, instead of an opaque nested dict.
        raw_anomalies = anomaly_result.get("anomalies", [])
        state.anomalies = [
            {
                "transaction_id": a["row"].get("transaction_id") or a["row"].get("payout_id") or "unknown",
                "vendor_id": a["row"].get("vendor_id"),
                "amount": a["row"].get("amount"),
                "reason": a["reason"],
                "severity": a["severity"],
            }
            for a in raw_anomalies
        ]
        
        if state.anomalies:
            anomaly_count = len(state.anomalies)
            severity_counts = {
                "high": len([a for a in state.anomalies if a.get("severity") == "high"]),
                "medium": len([a for a in state.anomalies if a.get("severity") == "medium"])
            }
            
            state.anomaly_summary = (
                f"Detected {anomaly_count} anomalies "
                f"({severity_counts['high']} high, {severity_counts['medium']} medium severity)"
            )
            logger.info(state.anomaly_summary)
        
        state.processing_stages_completed.append("anomaly_detection")
        if state.anomalies:
            state.stage_details["anomaly_detection"] = (
                f"{state.anomaly_summary} | Used: Z-score + Isolation Forest + Business Rules"
            )
        else:
            state.stage_details["anomaly_detection"] = "No anomalies detected (clean data)"
        
    except Exception as e:
        logger.error(f"Anomaly detection error: {e}")
    
    return state


async def response_formatting_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    Format final response with grounding information
    """
    # A legitimate zero-row result (state.query_results == []) must still be reported to the
    # user - only skip if no SQL was ever attempted and no error was raised.
    if state.sql_query is None and not state.execution_error:
        return state
    
    logger.info("Formatting response")
    
    try:
        if state.execution_error:
            # Never surface raw exception text to the user - still grounded (no invented
            # number), just phrased as an honest, actionable message. Raw error stays in logs.
            logger.error(f"Execution error (not shown to user): {state.execution_error}")
            state.final_answer = (
                "I wasn't able to retrieve that data. This question may not map to the "
                "available financial data (bank, account, or transaction records), "
                "or something went wrong running the query. Please try rephrasing your question."
            )
            return state
        
        # Build confidence components. Completeness/reliability reflect whether the query
        # executed successfully and was grounded in real data - NOT row count (a correct
        # single-row aggregate, e.g. a SUM, is just as "complete" as a 50-row list).
        execution_ok = state.sql_valid and not state.execution_error
        state.confidence_components = {
            "query_clarity": float(state.confidence_score),
            "data_completeness": 1.0 if execution_ok else 0.0,
            "result_reliability": 1.0 if execution_ok else 0.0,
            "result_count": len(state.query_results),
            "anomalies_detected": len(state.anomalies)
        }
        
        # Calculate composite confidence: query understanding (40%) + successful,
        # grounded execution (30%) + result reliability (30%). Row count plays no part.
        composite_confidence = (
            state.confidence_components["query_clarity"] * 0.4 +
            state.confidence_components["data_completeness"] * 0.3 +
            state.confidence_components["result_reliability"] * 0.3
        )
        state.composite_confidence = composite_confidence
        
        # Format answer
        confidence_text = _format_confidence(composite_confidence)
        
        if state.query_results:
            answer_intro = f"Based on the query results, I found {len(state.query_results)} matching record{'s' if len(state.query_results) != 1 else ''}."
        else:
            answer_intro = "I found no matching records for this question in the data - the answer is zero/none."
        
        # The full results table is sent separately as structured data (state.query_results)
        # and rendered by the frontend, so the text answer stays a short narrative summary.
        answer_parts = [
            answer_intro,
            f"Confidence: {confidence_text}",
        ]
        
        if state.anomaly_summary:
            answer_parts.append(f"Note: {state.anomaly_summary}")
        
        state.final_answer = "\n".join(answer_parts)
        
        # Store grounding info
        state.grounding_info = {
            "sql_query": state.sql_query,
            "data_source": "Verified execution against database",
            "execution_time_ms": 0,
            "rows_analyzed": len(state.query_results),
            "date_queried": datetime.now().isoformat(),
            "filters_applied": state.filters,
            "anomalies_detected": len(state.anomalies)
        }
        
        state.processing_stages_completed.append("response_formatting")
        state.stage_details["response_formatting"] = (
            f"Response formatted | Confidence: {state.confidence_score:.0%} | Results: {len(state.query_results)} row(s) | Grounding: SQL + verified data"
        )
        logger.info("Response formatted successfully")
        
    except Exception as e:
        logger.error(f"Response formatting error: {e}")
        state.final_answer = f"Error formatting response: {str(e)}"
    
    return state


async def export_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    Generate CSV export of results (bonus feature)
    """
    if not state.query_results:
        return state
    
    logger.info("Generating export")
    
    try:
        os.makedirs("exports", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join("exports", f"export_{timestamp}.csv")
        
        success, result = DataExporter.to_csv(state.query_results, filename)
        
        if success:
            state.export_filename = result
            state.processing_stages_completed.append("export")
            state.stage_details["export"] = f"Saved as {result}"
            logger.info(f"Export successful: {filename}")
        else:
            logger.warning(f"Export failed: {result}")
        
    except Exception as e:
        logger.error(f"Export error: {e}")
    
    return state


# ============================================================================
# CONDITIONAL ROUTING
# ============================================================================

def route_clarification(state: FinanceAssistantState) -> str:
    """Route based on clarification needs"""
    logger.info(f"route_clarification: confidence={state.confidence_score}, needs_clarification={state.needs_clarification}")
    if state.needs_clarification:
        logger.info("Routing to clarification node")
        return "clarification"
    logger.info("Routing to sql_generation node")
    return "sql_generation"


def route_validation(state: FinanceAssistantState) -> str:
    """Route based on SQL generation success"""
    if state.sql_query:
        return "sql_validation"
    return "response_formatting"


def route_execution(state: FinanceAssistantState) -> str:
    """Route based on SQL validation"""
    if state.sql_valid:
        return "query_execution"
    return "response_formatting"


# ============================================================================
# BUILD GRAPH
# ============================================================================

def build_finance_graph():
    """Build the LangGraph state machine"""
    graph = StateGraph(FinanceAssistantState)
    
    # Add nodes
    graph.add_node("classify", classify_query_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("sql_generation", sql_generation_node)
    graph.add_node("sql_validation", sql_validation_node)
    graph.add_node("query_execution", query_execution_node)
    graph.add_node("anomaly_detection", anomaly_detection_node)
    graph.add_node("response_formatting", response_formatting_node)
    graph.add_node("export", export_node)
    
    # Define edges
    graph.set_entry_point("classify")
    
    graph.add_conditional_edges(
        "classify",
        route_clarification,
        {
            "clarification": "clarification",
            "sql_generation": "sql_generation"
        }
    )
    
    graph.add_edge("clarification", END)
    
    graph.add_conditional_edges(
        "sql_generation",
        route_validation,
        {
            "sql_validation": "sql_validation",
            "response_formatting": "response_formatting"
        }
    )
    
    graph.add_conditional_edges(
        "sql_validation",
        route_execution,
        {
            "query_execution": "query_execution",
            "response_formatting": "response_formatting"
        }
    )
    
    graph.add_edge("query_execution", "anomaly_detection")
    graph.add_edge("anomaly_detection", "response_formatting")
    graph.add_edge("response_formatting", "export")
    graph.add_edge("export", END)
    
    return graph.compile()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _format_confidence(score: float) -> str:
    """Format confidence score as text"""
    if score >= 0.8:
        return f"🟢 High ({score:.0%})"
    elif score >= 0.6:
        return f"🟡 Medium ({score:.0%})"
    else:
        return f"🔴 Low ({score:.0%})"
