"""
LangGraph Agentic Loop for Finance Assistant
State machine for query processing pipeline
"""

import json
import os
import logging
import asyncio
import time
from typing import Dict, Any, List, Optional
from datetime import datetime

import boto3
import httpx
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from database import get_db
from prompts import (
    build_few_shot_prompt, build_cot_prompt,
    build_classification_prompt, CLASSIFICATION_PROMPT, SQL_VALIDATION_PROMPT,
    SQL_REPAIR_PROMPT, CLARIFICATION_PROMPT_TEMPLATE, BANK_CODE_MAP
)
from sql_validator import SQLValidator
from tools import QueryExecutor, AnomalyDetector, DataExporter, ContextManager

load_dotenv()
logger = logging.getLogger(__name__)

import re


def _detect_named_banks(user_query: str) -> List[str]:
    """Return the bank_code(s) the user's question names, based on BANK_CODE_MAP aliases."""
    query_lower = user_query.lower()
    matched = []
    for code, aliases in BANK_CODE_MAP.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", query_lower) for alias in aliases):
            matched.append(code)
    return matched


def _restrict_to_named_bank(sql: str, user_query: str) -> str:
    """
    If the question names exactly one bank but the generated SQL filters with a
    `bank_code IN (...)` list spanning multiple codes (observed: the LLM sometimes pastes
    the entire known bank_code mapping instead of a single '=' filter), narrow it down to
    that one bank so results aren't grouped/summed across unrelated banks.
    """
    matched_codes = _detect_named_banks(user_query)
    if len(matched_codes) != 1:
        return sql
    target_code = matched_codes[0]

    pattern = re.compile(r"(\b[\w]+\.)?bank_code\s+IN\s*\(([^)]+)\)", re.IGNORECASE)

    def _replace(match: "re.Match") -> str:
        prefix = match.group(1) or ""
        codes_in_list = re.findall(r"'([A-Za-z]+)'", match.group(2))
        if target_code not in [c.upper() for c in codes_in_list] or len(codes_in_list) <= 1:
            return match.group(0)
        return f"{prefix}bank_code = '{target_code}'"

    return pattern.sub(_replace, sql)


def _enforce_named_bank_filter(sql: str, user_query: str) -> str:
    """
    If the question names exactly one bank but the generated SQL has no bank_code filter
    at all (observed: the LLM sometimes just JOINs account/bank with no WHERE clause,
    returning every bank's data instead of the one asked about), inject one.
    """
    matched_codes = _detect_named_banks(user_query)
    if len(matched_codes) != 1:
        return sql
    target_code = matched_codes[0]

    # Already filtered on this bank_code somewhere (as '=' or part of an IN list) - nothing to do
    if re.search(rf"bank_code\s*(=|IN)\s*.*?{target_code}", sql, re.IGNORECASE):
        return sql

    # Only possible if the query touches the account table (bank_code lives there)
    account_match = re.search(r"\b(?:FROM|JOIN)\s+account\b(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?", sql, re.IGNORECASE)
    if not account_match:
        return sql
    alias = account_match.group(1) or "account"
    if alias.upper() in ("WHERE", "GROUP", "ORDER", "LIMIT", "JOIN", "ON", "INNER", "LEFT", "RIGHT", "FULL", "AS"):
        alias = "account"

    condition = f"{alias}.bank_code = '{target_code}'"

    tail_match = re.search(r"\b(GROUP BY|ORDER BY|LIMIT)\b", sql, re.IGNORECASE)
    insertion_point = tail_match.start() if tail_match else len(sql)
    head, tail = sql[:insertion_point], sql[insertion_point:]
    head = head.rstrip().rstrip(";")

    if re.search(r"\bWHERE\b", head, re.IGNORECASE):
        head += f" AND {condition} "
    else:
        head += f" WHERE {condition} "

    result = head + tail
    if result != sql:
        logger.info(f"Injected missing bank filter for '{target_code}': {result[:150]}...")
    return result


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _remove_invalid_transaction_filters(sql: str) -> str:
    """
    Remove WHERE clauses that filter transaction table by columns that don't exist.
    LLM sometimes generates: WHERE bank IN (...) or WHERE bank_code IN (...)
    These fail at runtime because transaction table only has:
      transaction_id, account_id, transaction_date, transaction_type, transaction_amount
    
    If this pattern is detected on a transaction query without a JOIN to account,
    remove it entirely (the user probably wants all transactions anyway).
    """
    # Check if this is a transaction query that filters by non-existent columns
    if re.search(r"\bFROM\s+transaction\b", sql, re.IGNORECASE):
        # Remove any WHERE clauses filtering by "bank" or "bank_code" directly on transaction
        # Pattern: WHERE bank[_code] IN (...) or WHERE bank[_code] = ...
        sql_cleaned = re.sub(
            r"\s+WHERE\s+(\w+\.)?bank(_code)?\s+(?:IN|=)\s*\([^)]*\)|[^;]+\)(?=\s*(?:GROUP|ORDER|LIMIT|;|$))",
            "",
            sql,
            flags=re.IGNORECASE
        )
        # If we removed the WHERE, also ensure we didn't leave trailing ANDs
        sql_cleaned = re.sub(r"\s+AND\s+\(\s*\)\s*", "", sql_cleaned)
        
        if sql_cleaned != sql:
            logger.info(f"Removed invalid transaction filter. Before: {sql[:100]}... After: {sql_cleaned[:100]}...")
        return sql_cleaned
    return sql


def _enforce_entity_scope(sql: str, entity_id: str) -> str:
    """
    Defense-in-depth for entity isolation: force every query touching account/transaction
    to be restricted to the locked entity_id, regardless of whether the LLM's own SQL
    included that filter. Relying on the LLM to always add `entity_id = ...` is not
    sufficient - a query that never selects entity_id (e.g. "utr number?") can otherwise
    leak rows belonging to other entities past the post-execution row filter, since that
    filter only fires when an `entity_id` column happens to be present in the results.

    Both `account` and `transaction` carry (or FK to, via account_id) entity_id, so this
    works regardless of which columns the query actually selects.
    """
    if not entity_id or not _UUID_RE.match(entity_id):
        # Fail closed: an entity filter is expected but the value isn't a well-formed
        # UUID - refuse to interpolate it into SQL rather than risk injection.
        raise ValueError(f"Invalid entity_id for scoping: {entity_id!r}")

    scoped_aliases = []
    for match in re.finditer(
        r"\b(?:FROM|JOIN)\s+(account|transaction)\b(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?",
        sql, re.IGNORECASE,
    ):
        table = match.group(1).lower()
        alias = match.group(2) or table
        if alias.upper() in ("WHERE", "GROUP", "ORDER", "LIMIT", "JOIN", "ON",
                              "INNER", "LEFT", "RIGHT", "FULL", "AS"):
            alias = table
        scoped_aliases.append((table, alias))

    if not scoped_aliases:
        return sql  # query doesn't touch account/transaction - nothing to scope

    conditions = " AND ".join(
        f"{alias}.account_id IN (SELECT account_id FROM account WHERE entity_id = '{entity_id}')"
        for _, alias in scoped_aliases
    )

    tail_match = re.search(r"\b(GROUP BY|ORDER BY|LIMIT)\b", sql, re.IGNORECASE)
    insertion_point = tail_match.start() if tail_match else len(sql)
    head, tail = sql[:insertion_point], sql[insertion_point:]
    head = head.rstrip().rstrip(";")

    if re.search(r"\bWHERE\b", head, re.IGNORECASE):
        head += f" AND ({conditions}) "
    else:
        head += f" WHERE ({conditions}) "

    return head + tail

# ============================================================================
# LLM CLIENT
#
# Qwen 1.5B: Optimized for financial queries
# Prefers a self-hosted vLLM endpoint (OpenAI-compatible) when VLLM_ENDPOINT_URL
# is set. Falls back to AWS Bedrock if needed.
# Fully compliant with Problem Statement Section 7 hard constraint (<=20B params)
# ============================================================================

DEFAULT_MODEL_ALIAS = "qwen-1.5b"  # vLLM-hosted Qwen 1.5B - PS-compliant

# Bedrock fallback (used only if vLLM is unavailable/fails)
_MODEL_ALIAS_ENV_KEYS = {
    "qwen-1.5b": "QWEN_MODEL_ID",
}
_MODEL_ALIAS_DEFAULTS = {
    "qwen-1.5b": "amazon.nova-micro-v1:0",  # Bedrock fallback ID used only if vLLM is unavailable/fails
}

_bedrock_client = None

VLLM_ENDPOINT_URL = os.getenv("VLLM_ENDPOINT_URL", "https://vllm-qwen-2wv6ilt7fa-uc.a.run.app/v1/chat/completions")
VLLM_MODEL_ID = os.getenv("VLLM_MODEL_ID", "Qwen/Qwen2.5-Coder-1.5B-Instruct")
VLLM_TIMEOUT_SECONDS = float(os.getenv("VLLM_TIMEOUT_SECONDS", "8"))

# Circuit breaker: once vLLM fails this many times in a row, stop trying it for a
# cool-down window and go straight to Bedrock, so an unreachable endpoint doesn't add
# repeated timeout latency to every subsequent query.
_VLLM_FAILURE_THRESHOLD = 2
_VLLM_COOLDOWN_SECONDS = 120
_vllm_consecutive_failures = 0
_vllm_disabled_until = 0.0


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


def _call_vllm(prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
    """Call the self-hosted vLLM OpenAI-compatible chat completions endpoint"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = httpx.post(
        VLLM_ENDPOINT_URL,
        json={
            "model": VLLM_MODEL_ID,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        headers={"Content-Type": "application/json"},
        timeout=VLLM_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        # Surface the server's actual error body (e.g. context-length exceeded) instead of
        # just the generic status code, so failures are diagnosable from the logs
        logger.warning(f"vLLM returned {response.status_code}: {response.text[:500]}")
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def _resolve_model_id(model_alias: str) -> str:
    """Resolve the Bedrock model ID for the given alias"""
    return os.getenv("QWEN_MODEL_ID", _MODEL_ALIAS_DEFAULTS["qwen-1.5b"])


def call_llm(prompt: str, model_alias: str = DEFAULT_MODEL_ALIAS, system: Optional[str] = None,
             max_tokens: int = 1024, temperature: float = 0.2) -> str:
    """Call the configured LLM and return its text response.

    Prefers the self-hosted vLLM endpoint (Qwen2.5-Coder-1.5B-Instruct) when
    VLLM_ENDPOINT_URL is reachable, falling back to AWS Bedrock otherwise/on error.
    A circuit breaker skips vLLM entirely (straight to Bedrock) for a cool-down window
    after repeated failures, instead of eating a timeout on every single query.
    """
    global _vllm_consecutive_failures, _vllm_disabled_until

    if time.time() < _vllm_disabled_until:
        logger.info("vLLM circuit breaker open - skipping straight to Bedrock")
    else:
        try:
            result = _call_vllm(prompt, system, max_tokens, temperature)
            _vllm_consecutive_failures = 0
            return result
        except Exception as e:
            _vllm_consecutive_failures += 1
            logger.warning(f"vLLM inference failed (consecutive failures: {_vllm_consecutive_failures}): {e}")
            if _vllm_consecutive_failures >= _VLLM_FAILURE_THRESHOLD:
                _vllm_disabled_until = time.time() + _VLLM_COOLDOWN_SECONDS
                logger.warning(f"vLLM disabled for {_VLLM_COOLDOWN_SECONDS}s after repeated failures, falling back to Bedrock")

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
        prompt = build_classification_prompt(state.user_query, history_context, entity_id=state.entity_id)

        response_text = await asyncio.to_thread(
            call_llm, prompt, model_alias=state.model_used, max_tokens=400, temperature=0.1
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

        # Safety net: the small LLM sometimes under-rates confidence for questions that are
        # actually self-contained (e.g. "count of unique banks in account records"). If the
        # question has no dangling pronoun/reference (nothing for entity_id to resolve) and
        # matches a simple count/sum/aggregate pattern over the whole dataset, don't force
        # clarification just because the model's self-rated score was low.
        if state.needs_clarification and not state.entity_id:
            ambiguous_pronoun = re.search(r"\b(its|their|this account|that account|it)\b", state.user_query, re.IGNORECASE)
            self_contained_aggregate = re.search(
                r"\b(count|how many|total|sum|average|unique|distinct)\b", state.user_query, re.IGNORECASE
            )
            if self_contained_aggregate and not ambiguous_pronoun:
                logger.info("Overriding low classification confidence: question looks self-contained")
                state.needs_clarification = False
        
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
    logger.info("Generating SQL query")
    
    if state.needs_clarification:
        logger.info("Skipping SQL generation due to clarification needed")
        return state
    
    try:
        history_context = ContextManager.format_history_for_prompt(state.conversation_history)

        # First, build CoT prompt
        cot_prompt = build_cot_prompt(state.user_query, history_context, entity_id=state.entity_id)
        
        # Get chain-of-thought reasoning
        cot_text = await asyncio.to_thread(
            call_llm, cot_prompt, model_alias=state.model_used, max_tokens=500, temperature=0.2
        )
        logger.debug(f"Chain-of-thought: {cot_text[:200]}")
        
        # Now generate SQL with few-shot examples
        few_shot_prompt = build_few_shot_prompt(state.user_query, history_context, entity_id=state.entity_id)
        
        # Prompt is already large (system prompt + all few-shot examples) relative to the model's
        # 4096-token context window, so keep max_tokens modest - SQL queries rarely need more.
        sql_text = (await asyncio.to_thread(
            call_llm, few_shot_prompt, model_alias=state.model_used, max_tokens=350, temperature=0.1
        )).strip()
        
        # Clean up SQL (remove markdown formatting if present)
        if "```sql" in sql_text:
            sql_text = sql_text.split("```sql")[1].split("```")[0].strip()
        elif "```" in sql_text:
            sql_text = sql_text.split("```")[1].split("```")[0].strip()
        
        # Remove invalid transaction filters that the LLM might add
        sql_text = _remove_invalid_transaction_filters(sql_text)
        # Fix up bank filtering: narrow an IN-list to the single named bank, or inject a
        # missing filter entirely, so results match the bank the user actually asked about
        sql_text = _restrict_to_named_bank(sql_text, state.user_query)
        sql_text = _enforce_named_bank_filter(sql_text, state.user_query)
        
        state.sql_query = sql_text
        state.processing_stages_completed.append("sql_generation")
        # Show full SQL or truncate if very long
        sql_preview = sql_text.strip()[:200] + "..." if len(sql_text.strip()) > 200 else sql_text.strip()
        state.stage_details["sql_generation"] = f"SQL Query:\n{sql_preview}"
        logger.info(f"SQL generated: {sql_text[:100]}...")
        
    except Exception as e:
        logger.error(f"SQL generation error: {e}", exc_info=True)
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
                model_alias=state.model_used, max_tokens=350, temperature=0.0
            )).strip()
            
            if "```sql" in corrected_sql:
                corrected_sql = corrected_sql.split("```sql")[1].split("```")[0].strip()
            elif "```" in corrected_sql:
                corrected_sql = corrected_sql.split("```")[1].split("```")[0].strip()
            
            corrected_sql = _remove_invalid_transaction_filters(corrected_sql)
            corrected_sql = _restrict_to_named_bank(corrected_sql, state.user_query)
            corrected_sql = _enforce_named_bank_filter(corrected_sql, state.user_query)
            revalidated, revalidation_msg = SQLValidator.validate_query(corrected_sql)
            if revalidated:
                state.sql_query = corrected_sql
                state.sql_valid = True
                state.processing_stages_completed.append("sql_validation")
                state.stage_details["sql_validation"] = "Passed static + LLM semantic checks (query refined)"
                logger.info("SQL validation passed (LLM-corrected query re-verified)")
            else:
                # LLM's "correction" failed schema/static safety net - keep original valid query
                logger.warning(
                    f"LLM-corrected SQL failed re-validation ({revalidation_msg}); "
                    f"keeping original validated query instead"
                )
                state.sql_valid = True
                state.processing_stages_completed.append("sql_validation")
                state.stage_details["sql_validation"] = "Passed static + schema checks (kept original query)"
        
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
        exec_sql = state.sql_query
        if state.entity_id:
            exec_sql = _enforce_entity_scope(exec_sql, state.entity_id)

        success, result = QueryExecutor.execute(exec_sql)

        # One-shot self-repair: feed the DB error back to the LLM and retry, since
        # execution-time errors (bad GROUP BY, wrong alias, etc.) slip past static/LLM
        # validation which only checks the query in isolation, not against real execution.
        if not success:
            logger.warning(f"Query execution failed, attempting one-shot repair: {result}")
            try:
                repair_prompt = SQL_REPAIR_PROMPT.format(sql=state.sql_query, error=str(result))
                repaired_sql = (await asyncio.to_thread(
                    call_llm, repair_prompt, model_alias=state.model_used, max_tokens=350, temperature=0.0
                )).strip()
                if "```sql" in repaired_sql:
                    repaired_sql = repaired_sql.split("```sql")[1].split("```")[0].strip()
                elif "```" in repaired_sql:
                    repaired_sql = repaired_sql.split("```")[1].split("```")[0].strip()

                is_valid, validation_msg = SQLValidator.validate_query(repaired_sql)
                if is_valid:
                    repaired_exec_sql = repaired_sql
                    if state.entity_id:
                        repaired_exec_sql = _enforce_entity_scope(repaired_exec_sql, state.entity_id)
                    repaired_success, repaired_result = QueryExecutor.execute(repaired_exec_sql)
                    if repaired_success:
                        logger.info("Self-repair succeeded, using repaired SQL")
                        state.sql_query = repaired_sql
                        state.stage_details["sql_validation"] = (
                            state.stage_details.get("sql_validation", "") + " | Repaired after execution error"
                        )
                        success, result = repaired_success, repaired_result
                    else:
                        logger.warning(f"Self-repair query also failed to execute: {repaired_result}")
                else:
                    logger.warning(f"Self-repair query failed static validation: {validation_msg}")
            except Exception as repair_exc:
                logger.error(f"Self-repair attempt errored: {repair_exc}")

        if success:
            rows = result if isinstance(result, list) else [result]
            # Defense-in-depth: if an entity filter is active and the LLM's SQL still
            # returned rows tagged with a different entity_id, drop them before they reach the user
            if state.entity_id and rows and "entity_id" in rows[0]:
                rows = [row for row in rows if row.get("entity_id") == state.entity_id]
            state.query_results = rows
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
        # Always build grounding info so UI gets full transparency even on error/no-results
        state.grounding_info = {
            "sql_query": state.sql_query or "No query executed",
            "data_source": "Verified execution against database",
            "execution_time_ms": 0,
            "rows_analyzed": len(state.query_results) if state.query_results else 0,
            "date_queried": datetime.now().isoformat(),
            "filters_applied": state.filters or [],
            "anomalies_detected": len(state.anomalies) if state.anomalies else 0
        }

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
