"""
LLM Prompts for TBX Finance Assistant
Includes few-shot examples, system prompts, and response formatting
TBX Schema: bank, account, transaction
"""

# Mirrors the "KNOWN bank_code -> bank_name MAPPING" documented in
# SQL_GENERATION_SYSTEM_PROMPT below - used in code (not just prompt text) to detect
# when a user names exactly one bank, so a generated query that lumps in every known
# bank_code can be corrected post-hoc (see langgraph_flow.py _restrict_to_named_bank).
BANK_CODE_MAP = {
    "HDFC": ["hdfc"],
    "ICIC": ["icici"],
    "SBIN": ["sbin", "sbi", "state bank"],
    "UTIB": ["utib", "axis"],
    "KKBK": ["kkbk", "kotak"],
    "CNRB": ["cnrb", "canara"],
    "UBIN": ["ubin", "union bank"],
    "AUBL": ["aubl", "au small finance", "au bank"],
    "TMBL": ["tmbl", "tamilnad"],
    "RATN": ["ratn", "rbl"],
}

# ============================================================================
# SYSTEM PROMPT FOR SQL GENERATION
# ============================================================================
SQL_GENERATION_SYSTEM_PROMPT = """Convert natural language questions into SQL queries for TBX financial data.

SCHEMA (all singular table names):
- bank: bank_code, bank_name
- account: account_id, account_number, available_balance, bank_code
- transaction: transaction_id, account_id, transaction_date, transaction_type ('credit'/'debit'), transaction_amount, description, transaction_reference_id, utr_number

KEY RULES:
1. Table names are SINGULAR: transaction (NOT transactions), account (NOT accounts), bank (NOT banks)
2. available_balance and transaction_amount are VARCHAR - always CAST to DECIMAL before math operations
3. Use SUM() only for "total"/"sum" of money amounts - use COUNT(*) for "sum of accounts/transactions"
4. account_number is a digit string (e.g., '50200013729069'); account_id is a UUID
5. Bank mapping: HDFC→HDFC, ICIC→ICICI, SBIN→SBI, UTIB→Axis, KKBK→Kotak, CNRB→Canara, UBIN→Union, AUBL→AU, TMBL→Tamilnad, RATN→RBL
6. Only filter by date if user explicitly mentions a time period
7. For grouping by date: use CAST(transaction_date AS DATE)
8. Wrap aggregates in COALESCE: COALESCE(SUM(CAST(x AS DECIMAL)), 0)
9. Never copy example values into your query - use only values from the user's question

RETURN ONLY THE SQL QUERY - no explanation."""

# ============================================================================
# FEW-SHOT EXAMPLES FOR SQL GENERATION (TBX Schema)
# ============================================================================
SQL_EXAMPLES = [
    {
        "question": "How many accounts are there?",
        "sql": "SELECT COUNT(*) as total_accounts FROM account"
    },
    {
        "question": "What's the total available balance?",
        "sql": "SELECT COALESCE(SUM(CAST(available_balance AS DECIMAL)), 0) as total_balance FROM account"
    },
    {
        "question": "Show all transactions from HDFC",
        "sql": """SELECT t.*, b.bank_name
FROM transaction t
JOIN account a ON t.account_id = a.account_id
JOIN bank b ON a.bank_code = b.bank_code
WHERE b.bank_code = 'HDFC'
LIMIT 100"""
    },
    {
        "question": "What's the balance for account 50200013729069?",
        "sql": "SELECT account_number, CAST(available_balance AS DECIMAL) as balance FROM account WHERE account_number = '50200013729069'"
    }
]

# ============================================================================
# PROMPT FOR CHAIN-OF-THOUGHT SQL GENERATION
# ============================================================================
COT_PROMPT_TEMPLATE = """Question: {question}

Tables: bank (bank_code, bank_name), account (account_id, account_number, available_balance, bank_code), transaction (transaction_id, account_id, transaction_date, transaction_type, transaction_amount)

Think step-by-step:
1. Which tables needed? (bank, account, transaction - always use singular names)
2. What filters? (only add date if time period mentioned)
3. What calculation? (COUNT, SUM, AVG?)
4. How to join?
5. Sort and limit?

CRITICAL: Use FROM transaction (not transactions), FROM account (not accounts), FROM bank (not banks)"""

# ============================================================================
# CLASSIFICATION PROMPT (Determine query type and confidence)
# ============================================================================
CLASSIFICATION_PROMPT = """{history_context}{entity_context}Question: "{question}"

Tables: bank (bank_code, bank_name), account (account_id, account_number, available_balance, bank_code), transaction (transaction_id, account_id, transaction_date, transaction_type, transaction_amount)

Classify:
1. intent: account_balances, transaction_analysis, bank_summary, specific_account, transaction_search, other
2. entities: Which accounts/banks/programs mentioned?
3. filters: What conditions? (date range, bank_code, balance range, etc.)
4. confidence: high/medium/low

Respond in JSON format:
{{
    "intent": "...",
    "entities": {{}},
    "filters": {{}},
    "confidence_score": 0.0-1.0,
    "clarification_questions": []
}}"""

# ============================================================================
# CLARIFICATION PROMPT (Ask user for missing info)
# ============================================================================
CLARIFICATION_PROMPT_TEMPLATE = """I need clarification to answer your question accurately:

Your question: "{question}"

{clarification_questions}

Please provide the missing details, then I can give you an accurate answer."""

# ============================================================================
# VALIDATION PROMPT (Validate SQL correctness)
# ============================================================================
SQL_VALIDATION_PROMPT = """Review this SQL query:

{sql}

Check:
1. Table names SINGULAR (transaction, account, bank - NOT plural)
2. Valid SQL syntax
3. CAST numeric columns before SUM/AVG: COALESCE(CAST(x AS DECIMAL), 0)
4. Only bank codes: HDFC, ICIC, SBIN, UTIB, KKBK, CNRB, UBIN, AUBL, TMBL, RATN
5. Answers the question correctly

Fix any issues and return ONLY the corrected SQL (no explanation)."""

# ============================================================================
# REPAIR PROMPT (Fix a query that failed)
# ============================================================================
SQL_REPAIR_PROMPT = """Fix this failed SQL query:

{sql}

Error: {error}

Tables: bank, account, transaction (all singular). Remember:
- CAST(available_balance AS DECIMAL) and CAST(transaction_amount AS DECIMAL) before math
- GROUP BY all non-aggregated columns
- Use singular table names

Return ONLY the corrected SQL (no explanation)."""

# ============================================================================
# ANOMALY EXPLANATION PROMPT
# ============================================================================
ANOMALY_EXPLANATION_PROMPT = """This transaction looks unusual:

Amount: {{current_amount:.2f}}
Historical Average: {{avg_amount:.2f}}
Multiplier: {{multiple}}x

Briefly explain why it stands out (1-2 sentences)."""

# ============================================================================
# CONFIDENCE SCORING COMPONENTS
# ============================================================================
CONFIDENCE_COMPONENTS = {
    "temperature": "Model uncertainty (lower = higher confidence)",
    "data_completeness": "Percentage of requested data available",
    "query_clarity": "How unambiguous was the user's question",
    "result_reliability": "How confident we are in the results"
}

def build_few_shot_prompt(user_question: str, history_context: str = "", entity_id: str = None) -> str:
    """Build few-shot prompt with examples, optionally grounded in prior turns and scoped to one entity_id"""
    examples_text = ""
    for i, example in enumerate(SQL_EXAMPLES, 1):
        examples_text += f"""
Example {i}:
Q: {example['question']}
SQL: {example['sql']}
---
"""
    
    entity_instruction = ""
    if entity_id:
        entity_instruction = f"\nNOTE: Filter results to entity_id = '{entity_id}' only."

    return f"""{SQL_GENERATION_SYSTEM_PROMPT}
{entity_instruction}
{history_context}{examples_text}
Now, for this question:
{user_question}

Generate the SQL query:"""

def build_cot_prompt(user_question: str, history_context: str = "", entity_id: str = None) -> str:
    """Build chain-of-thought prompt, optionally grounded in prior turns and scoped to one entity_id"""
    prompt = f"{history_context}{COT_PROMPT_TEMPLATE.format(question=user_question)}"
    if entity_id:
        prompt += f"\n\nNote: Results must be restricted to entity_id = '{entity_id}' only."
    return prompt

def build_classification_prompt(user_question: str, history_context: str = "", entity_id: str = None) -> str:
    """Build the query classification prompt, optionally grounded in prior conversation turns and scoped to one entity_id"""
    entity_context = (
        f"The user has selected entity_id = '{entity_id}' in the UI. Treat pronouns like "
        f"'its'/'their'/'this account' as referring to accounts owned by this entity, and do "
        f"not ask for clarification on which account/entity - use entity_id = '{entity_id}' "
        f"instead.\n\n"
        if entity_id else ""
    )
    return CLASSIFICATION_PROMPT.format(question=user_question, history_context=history_context, entity_context=entity_context)
