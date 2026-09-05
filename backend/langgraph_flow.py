"""
LangGraph Agentic Loop for Finance Assistant
State machine for query processing pipeline
"""

import json
import os
import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

import httpx
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from database import get_db
from prompts import (
    build_few_shot_prompt, build_response_prompt, build_repair_prompt,
    build_classification_prompt, CLARIFICATION_PROMPT_TEMPLATE, CLASSIFICATION_JSON_SCHEMA
)
from sql_validator import SQLValidator
from tools import QueryExecutor, AnomalyDetector, DataExporter, ContextManager
from query_cache import get_cached_sql, store_verified_sql
from crypto_utils import decrypt_results

load_dotenv()
logger = logging.getLogger(__name__)

# ============================================================================
# LLM CLIENT
#
# Primary: Qwen2.5-Coder-1.5B-Instruct, served locally (Ollama) or via vLLM on
# GCP - both speak the same OpenAI-compatible /v1/chat/completions schema, so
# only LLM_BASE_URL changes between the two, no code changes.
# Fallback: AWS Bedrock (Nova Micro etc.), kept switchable via model_alias.
# ============================================================================

DEFAULT_MODEL_ALIAS = "qwen2.5-coder-1.5b"

# Bedrock model aliases (fallback path)
_BEDROCK_MODEL_ALIAS_ENV_KEYS = {
    "amazon.nova-micro": "NOVA_MICRO_MODEL_ID",
    "llama3-1-8b": "LLAMA_8B_MODEL_ID",
    "mistral-7b": "MISTRAL_7B_MODEL_ID",
    "llama4-scout-17b": "LLAMA_SCOUT_17B_MODEL_ID",
}
_BEDROCK_MODEL_ALIAS_DEFAULTS = {
    "amazon.nova-micro": "amazon.nova-micro-v1:0",
    "llama3-1-8b": "meta.llama3-1-8b-instruct-v1:0",
    "mistral-7b": "mistral.mistral-7b-instruct-v0:2",
    "llama4-scout-17b": "meta.llama4-scout-17b-instruct-v1:0",
}

_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        import boto3  # only imported if the Bedrock fallback is actually used
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
    return _bedrock_client


def _call_bedrock(prompt: str, model_alias: str, system: Optional[str],
                   max_tokens: int, temperature: float) -> str:
    alias = model_alias if model_alias in _BEDROCK_MODEL_ALIAS_ENV_KEYS else "amazon.nova-micro"
    model_id = os.getenv(_BEDROCK_MODEL_ALIAS_ENV_KEYS[alias], _BEDROCK_MODEL_ALIAS_DEFAULTS[alias])
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


def _call_openai_compatible(prompt: str, system: Optional[str],
                             max_tokens: int, temperature: float,
                             response_format: Optional[Dict[str, Any]] = None) -> str:
    """Call a local Ollama / GCP vLLM endpoint via the OpenAI-compatible chat completions API.
    response_format: an OpenAI-style {"type": "json_schema", "json_schema": {...}} dict - vLLM
    enforces this via guided decoding (confirmed working against the deployed vLLM 0.28 endpoint;
    the older guided_json/guided_choice params are deprecated on that version and were confirmed
    NOT enforced, so this is the only structured-output path used here)."""
    base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    model_name = os.getenv("LLM_MODEL_NAME", "qwen2.5-coder:1.5b-instruct")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format:
        body["response_format"] = response_format

    response = httpx.post(f"{base_url}/chat/completions", json=body, timeout=60.0)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def call_llm(prompt: str, model_alias: str = DEFAULT_MODEL_ALIAS, system: Optional[str] = None,
             max_tokens: int = 1024, temperature: float = 0.2,
             response_format: Optional[Dict[str, Any]] = None) -> str:
    """Call the configured LLM and return its text response.
    response_format is only honored on the OpenAI-compatible path (see _call_openai_compatible);
    the Bedrock fallback path ignores it and relies on prompt-level JSON instructions instead."""
    if model_alias in _BEDROCK_MODEL_ALIAS_ENV_KEYS:
        return _call_bedrock(prompt, model_alias, system, max_tokens, temperature)
    return _call_openai_compatible(prompt, system, max_tokens, temperature, response_format)

# ============================================================================
# STATE DEFINITION
# ============================================================================
class FinanceAssistantState(BaseModel):
    """State for the LangGraph"""
    user_query: str
    conversation_history: List[Dict[str, Any]] = []
    entity_id: Optional[str] = None  # Restricts results to a single entity, if selected in the UI

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
    cache_hit: bool = False

    # Execution stage
    query_results: List[Dict[str, Any]] = []
    execution_error: Optional[str] = None
    repair_attempted: bool = False

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
    model_used: str = DEFAULT_MODEL_ALIAS
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
        prompt = build_classification_prompt(state.user_query, history_context, entity_id=state.entity_id)

        response_text = await asyncio.to_thread(
            call_llm, prompt, model_alias=state.model_used, max_tokens=1024, temperature=0.1,
            response_format=CLASSIFICATION_JSON_SCHEMA,
        )

        # Structured output (response_format) guarantees valid JSON on the OpenAI-compatible
        # path; this brace-hunting stays only as a defensive fallback for the Bedrock path,
        # which ignores response_format.
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
        state.stage_details["classification"] = (
            f"Intent: {state.intent} · confidence {state.confidence_score:.0%}"
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


def _strip_sql_markdown(sql_text: str) -> str:
    """Remove markdown code-fences a model may wrap around a SQL response"""
    if "```sql" in sql_text:
        return sql_text.split("```sql")[1].split("```")[0].strip()
    elif "```" in sql_text:
        return sql_text.split("```")[1].split("```")[0].strip()
    return sql_text.strip()


def _result_signature(rows: List[Dict[str, Any]]) -> str:
    """Order-independent, type-normalized signature of a query result, for majority voting
    across execution-guided self-consistency candidates (see sql_generation_node)."""
    normalized = sorted(tuple(sorted((k, str(v)) for k, v in row.items())) for row in rows)
    return str(normalized)


async def sql_generation_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    Generate SQL query with few-shot examples, or reuse a previously execution-verified
    query for an equivalent question (verified-query cache) - skips the LLM call entirely
    when a repeat/near-identical question was already answered correctly before.
    """
    logger.info("Generating SQL query")

    if state.needs_clarification:
        logger.info("Skipping SQL generation due to clarification needed")
        return state

    cached_sql = get_cached_sql(state.user_query, entity_id=state.entity_id)
    if cached_sql:
        state.sql_query = cached_sql
        state.cache_hit = True
        state.processing_stages_completed.append("sql_generation")
        state.stage_details["sql_generation"] = "Reused previously verified query (cache hit)"
        logger.info("Verified-query cache hit, skipping LLM SQL generation")
        return state

    try:
        history_context = ContextManager.format_history_for_prompt(state.conversation_history)
        few_shot_prompt = build_few_shot_prompt(state.user_query, history_context, entity_id=state.entity_id)
        n_samples = max(1, int(os.getenv("SQL_SELF_CONSISTENCY_N", "3")))

        if n_samples <= 1:
            # Self-consistency disabled: single low-temperature shot, unchanged from before.
            sql_text = _strip_sql_markdown(await asyncio.to_thread(
                call_llm, few_shot_prompt, model_alias=state.model_used, max_tokens=1024, temperature=0.1
            ))
            state.sql_query = sql_text
            first_line = sql_text.strip().splitlines()[0] if sql_text.strip() else ""
            state.stage_details["sql_generation"] = f"{first_line[:80]}..." if len(sql_text) > 80 else first_line
        else:
            # Execution-guided self-consistency: sample N candidates concurrently (higher
            # temperature for diversity), trial-execute each, and majority-vote on the
            # normalized result - a well-evidenced small-model text-to-SQL accuracy booster
            # (reduces schema-linking/join/logical-form errors) since it cross-checks candidates
            # against real data instead of trusting a single generation. See INTERNAL_NOTES.md.
            raw_candidates = await asyncio.gather(*[
                asyncio.to_thread(
                    call_llm, few_shot_prompt, model_alias=state.model_used,
                    max_tokens=1024, temperature=0.4
                )
                for _ in range(n_samples)
            ])
            candidates = [_strip_sql_markdown(c) for c in raw_candidates]

            groups: Dict[str, List[str]] = {}
            first_working: Optional[str] = None
            for sql in candidates:
                success, result = QueryExecutor.execute(sql)
                if not success:
                    continue
                if first_working is None:
                    first_working = sql
                sig = _result_signature(result if isinstance(result, list) else [result])
                groups.setdefault(sig, []).append(sql)

            if groups:
                best_sig = max(groups, key=lambda s: len(groups[s]))
                winner = groups[best_sig][0]
                agreement = len(groups[best_sig])
                state.stage_details["sql_generation"] = (
                    f"Self-consistency: {agreement}/{n_samples} candidates agreed"
                )
                logger.info(f"Self-consistency: {agreement}/{n_samples} candidates agreed on a result")
            else:
                # Nothing executed - keep the first candidate; sql_repair_node gets one
                # bounded shot at fixing it using the real error, same as the N=1 path.
                winner = candidates[0]
                state.stage_details["sql_generation"] = (
                    f"Self-consistency: 0/{n_samples} candidates executed, falling through to repair"
                )
                logger.info("Self-consistency: no candidate executed successfully")

            state.sql_query = winner

        state.processing_stages_completed.append("sql_generation")
        logger.info(f"SQL generated: {state.sql_query[:100]}...")

    except Exception as e:
        logger.error(f"SQL generation error: {e}")
        state.execution_error = f"SQL generation failed: {str(e)}"

    return state


async def sql_validation_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    Static SQL safety/schema validation (syntax, dangerous ops, allowed tables, LIMIT cap).
    Deliberately does NOT ask the LLM to "review" its own SQL with no error to react to -
    see sql_repair_node, which regenerates using the real DB error instead, only if execution
    actually fails.
    """
    if not state.sql_query or state.execution_error:
        return state

    logger.info("Validating SQL")

    is_valid, validation_msg = SQLValidator.validate_query(state.sql_query)
    if is_valid:
        state.sql_valid = True
        state.processing_stages_completed.append("sql_validation")
        state.stage_details["sql_validation"] = "Passed static checks"
    else:
        state.sql_valid = False
        state.sql_errors.append(validation_msg)
        logger.warning(f"Static validation failed: {validation_msg}")

    return state


async def sql_repair_node(state: FinanceAssistantState) -> FinanceAssistantState:
    """
    Execution-feedback self-repair: only reached once, only after a real execution failure.
    Feeds the actual DB error back to the model instead of asking it to blindly re-review SQL.
    """
    state.repair_attempted = True
    logger.info(f"Attempting SQL repair after execution error: {state.execution_error}")

    try:
        repair_prompt = build_repair_prompt(state.sql_query, state.execution_error, state.user_query)
        repaired_sql = _strip_sql_markdown(await asyncio.to_thread(
            call_llm, repair_prompt, model_alias=state.model_used, max_tokens=1024, temperature=0.0
        ))

        is_valid, validation_msg = SQLValidator.validate_query(repaired_sql)
        if is_valid:
            state.sql_query = repaired_sql
            state.sql_valid = True
            state.execution_error = None  # clear so the retry gets a clean shot
            state.stage_details["sql_repair"] = "Regenerated using the real DB error, re-validated"
            logger.info("SQL repair produced a statically valid query, retrying execution")
        else:
            logger.warning(f"Repaired SQL failed static validation ({validation_msg}); giving up")

    except Exception as e:
        logger.error(f"SQL repair error: {e}")

    state.processing_stages_completed.append("sql_repair")
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
            rows = result if isinstance(result, list) else [result]
            # Defense-in-depth: if an entity filter is active, drop any row tagged with a
            # different entity_id before it ever reaches decryption/the user - a backstop for
            # the (rare) case the LLM's SQL didn't filter by entity_id itself.
            if state.entity_id and rows and "entity_id" in rows[0]:
                rows = [row for row in rows if row.get("entity_id") == state.entity_id]
            # Decrypt sensitive columns (account_number, utr_number) here, on the final,
            # already-small result set that's about to be shown/exported - never eagerly, and
            # never before/during filtering (ciphertext can't be filtered on anyway; see
            # sql_validator.py's _check_encrypted_column_usage). Self-consistency's trial
            # executions in sql_generation_node vote on raw (undecrypted) results since the
            # stored ciphertext is already a stable per-row identifier - this is the one point
            # where the values that actually reach the user get decrypted.
            state.query_results = decrypt_results(rows)
            state.execution_error = None  # clear any stale error from a pre-repair attempt
            state.processing_stages_completed.append("query_execution")
            state.stage_details["query_execution"] = f"{len(state.query_results)} row(s) returned"
            logger.info(f"Query execution successful, {len(state.query_results)} rows returned")
            # Cache only SQL that has actually executed without error - never a failed or
            # repaired-but-unverified query.
            store_verified_sql(state.user_query, state.sql_query, entity_id=state.entity_id)
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
        state.stage_details["anomaly_detection"] = (
            state.anomaly_summary if state.anomalies else "No anomalies detected"
        )
        
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
                "available financial data (vendor spend, payouts, reconciliation status), "
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
            f"Composite confidence {composite_confidence:.0%}"
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
    if state.needs_clarification:
        return "clarification"
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


def route_repair(state: FinanceAssistantState) -> str:
    """After execution: on failure, repair once (execution-feedback); otherwise move on.
    The repair attempt is capped at exactly one retry via state.repair_attempted."""
    if state.execution_error and not state.repair_attempted:
        return "sql_repair"
    return "anomaly_detection"


def route_after_repair(state: FinanceAssistantState) -> str:
    """If repair produced a statically-valid query, retry execution once; otherwise give up."""
    if state.sql_valid and state.execution_error is None:
        return "query_execution"
    return "anomaly_detection"


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
    graph.add_node("sql_repair", sql_repair_node)
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

    graph.add_conditional_edges(
        "query_execution",
        route_repair,
        {
            "sql_repair": "sql_repair",
            "anomaly_detection": "anomaly_detection"
        }
    )

    graph.add_conditional_edges(
        "sql_repair",
        route_after_repair,
        {
            "query_execution": "query_execution",
            "anomaly_detection": "anomaly_detection"
        }
    )

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
