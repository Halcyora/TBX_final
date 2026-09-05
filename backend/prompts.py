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

DATABASE SCHEMA:
- bank: bank_code, bank_name
- account: account_id, account_number, available_balance, bank_code, entity_id
- transaction (SINGULAR - NOT plural): transaction_id, account_id, transaction_date, transaction_type, description, transaction_amount, transaction_reference_id, utr_number
  ** IMPORTANT: transaction table does NOT have bank, bank_code, or account_number columns **
  ** transaction.description holds free-text like 'UPI-NETFLIX-...', 'NEFT - HDFC0002678 - ... - GST PAYMENT' - the ONLY place merchant/counterparty/payment-purpose names (e.g. Netflix, Amazon, GST, EMI) appear **

CRITICAL TABLE RELATIONSHIPS:
1. transaction links to account via: transaction.account_id = account.account_id
2. account links to bank via: account.bank_code = bank.bank_code
3. To query transaction data with bank filter: JOIN account THEN JOIN bank
4. To query transaction data with account filter: only JOIN account

COLUMN NOTES:
- transaction.transaction_type is ONLY 'credit' or 'debit'
- account.available_balance and transaction.transaction_amount are VARCHAR - CAST to DECIMAL
- account.bank_code is the FK to bank.bank_code (NOT a "bank" column)

KEY RULES:
1. Table names SINGULAR: FROM transaction (NOT transactions), FROM account (NOT accounts)
2. Do NOT filter transaction by "bank" directly - bank info is in account table only
3. Use SUM() for money totals, COUNT(*) for counting rows
4. account_number is the numeric value users mention; account_id is the UUID
5. Only add WHERE date clause if user mentions a specific time period
6. For date grouping: CAST(transaction_date AS DATE)
7. Wrap aggregates: COALESCE(SUM(CAST(x AS DECIMAL)), 0) to return 0 not NULL
8. If the user names a merchant/counterparty/payment purpose that is NOT a bank (e.g. Netflix, Amazon, GST, EMI, salary), filter with transaction.description LIKE '%KEYWORD%' (case-insensitive, uppercase the keyword)
9. Return ONLY SQL - no explanations, no markdown, no wrapping

EXAMPLE - DON'T DO THIS (WRONG):
- SELECT COUNT(*) FROM transaction WHERE bank IN ('HDFC', 'ICIC') - "bank" column doesn't exist!

EXAMPLE - DO THIS (CORRECT):
- SELECT COUNT(*) FROM transaction - simple count
- SELECT COUNT(t.*) FROM transaction t JOIN account a ON t.account_id = a.account_id WHERE a.bank_code = 'HDFC' - filtered by bank
- SELECT COUNT(*) FROM transaction WHERE description LIKE '%NETFLIX%' - filtered by merchant name in description"""

# ============================================================================
# FEW-SHOT EXAMPLES FOR SQL GENERATION (TBX Schema)
# ============================================================================
SQL_EXAMPLES = [
    {
        "question": "How many accounts do we have?",
        "sql": "SELECT COUNT(*) as account_count FROM account"
    },
    {
        "question": "What is the total balance of all accounts?",
        "sql": "SELECT COALESCE(SUM(CAST(available_balance AS DECIMAL)), 0) as total_balance FROM account"
    },
    {
        "question": "What is the total number of transactions?",
        "sql": "SELECT COUNT(*) as total_transactions FROM transaction"
    },
    {
        "question": "Show transactions from HDFC bank",
        "sql": """SELECT t.transaction_id, t.transaction_date, t.transaction_type, CAST(t.transaction_amount AS DECIMAL) as amount
FROM transaction t
JOIN account a ON t.account_id = a.account_id
WHERE a.bank_code = 'HDFC'
LIMIT 50"""
    },
    {
        "question": "What is the available balance for account 50200013729069?",
        "sql": "SELECT CAST(available_balance AS DECIMAL) as balance FROM account WHERE account_number = '50200013729069'"
    },
    {
        "question": "How many credit vs debit transactions are there?",
        "sql": "SELECT transaction_type, COUNT(*) as count, COALESCE(SUM(CAST(transaction_amount AS DECIMAL)), 0) as total_amount FROM transaction GROUP BY transaction_type"
    },
    {
        "question": "How many transactions are there for Netflix?",
        "sql": "SELECT COUNT(*) as netflix_transaction_count FROM transaction WHERE description LIKE '%NETFLIX%'"
    }
]

# ============================================================================
# PROMPT FOR CHAIN-OF-THOUGHT SQL GENERATION
# ============================================================================
COT_PROMPT_TEMPLATE = """Question: {question}

Tables: bank (bank_code, bank_name), account (account_id, account_number, available_balance, bank_code), transaction (transaction_id, account_id, transaction_date, transaction_type, description, transaction_amount)

Think step-by-step:
1. Which tables needed? (bank, account, transaction - always use singular names)
2. What filters? (only add date if time period mentioned; merchant/counterparty names like Netflix/Amazon/GST/EMI go in transaction.description LIKE '%NAME%')
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

CONFIDENCE CALIBRATION - a question is HIGH confidence (>= 0.8) whenever it can be answered
with a single COUNT/SUM/AVG/GROUP BY query over the whole table(s) and does NOT depend on
something missing from the question itself. Do NOT lower confidence just because the
question doesn't name a specific account/bank/entity - "how many", "count of", "total",
"unique"/"distinct" questions about the whole dataset are self-contained and unambiguous.
Only use LOW confidence (< 0.6) when the question uses a pronoun/reference with nothing to
resolve it to (e.g. "its balance", "that account") or names an account/bank/entity that
doesn't exist in the schema.
Examples:
- "count of unique banks in account records" -> confidence_score: 0.95 (self-contained: SELECT COUNT(DISTINCT bank_code) FROM account)
- "how many accounts do we have?" -> confidence_score: 0.95 (self-contained)
- "what's its balance?" (no entity/account selected) -> confidence_score: 0.3 (ambiguous pronoun, nothing to resolve "its" to)

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
4. CRITICAL: Do NOT add WHERE clauses or bank filters if they are not in the query!
5. CRITICAL: Do NOT reference bank or bank_code columns on transaction table (they don't exist in transaction table).
6. If the query is already valid and correct, return it EXACTLY as is without changes.

Return ONLY the SQL query (no explanation, no markdown)."""

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
