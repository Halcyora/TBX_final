"""
LLM Prompts for TBX Finance Assistant
Includes few-shot examples, system prompts, and response formatting
TBX Schema: bank, account, transaction
"""

import re
from typing import Dict, List, Optional

# ============================================================================
# SYSTEM PROMPT FOR SQL GENERATION
# ============================================================================
SQL_GENERATION_SYSTEM_PROMPT = """You are an expert SQL developer for TBX financial data analysis.
Your job is to convert natural language questions into precise SQL queries.

DATABASE SCHEMA (TBX Finance Assistant):

bank:
- bank_code (VARCHAR, PRIMARY KEY): Bank identifier code (e.g., HDFC, ICIC, SBIN, UTIB)
- bank_name (VARCHAR): Canonical bank name in all-caps (e.g., HDFC BANK LIMITED)

KNOWN bank_code -> bank_name MAPPING (do not invent a bank_code from an abbreviation; several
codes do NOT match the common short name, e.g. State Bank of India / "SBI" is code SBIN, not
"SBI"; Axis Bank is code UTIB, not "AXIS". Other banks may also exist beyond this list - if the
user names one not below, filter with `UPPER(b.bank_name) LIKE UPPER('%<key part of name>%')`
instead of guessing a code):
- HDFC -> HDFC BANK LIMITED
- ICIC -> ICICI BANK LIMITED
- SBIN -> STATE BANK OF INDIA (user may say "SBI" or "State Bank")
- UTIB -> AXIS BANK LIMITED (user may say "Axis")
- KKBK -> KOTAK MAHINDRA BANK LIMITED (user may say "Kotak")
- CNRB -> CANARA BANK
- UBIN -> UNION BANK OF INDIA
- AUBL -> AU SMALL FINANCE BANK LIMITED
- TMBL -> TAMILNAD MERCANTILE BANK LIMITED
- RATN -> RBL BANK LIMITED (user may say "RBL")

account:
- account_id (VARCHAR, PRIMARY KEY): Unique account identifier (UUID)
- entity_id (VARCHAR): Customer/entity that owns this account (UUID)
- account_number (VARCHAR): Account number - ENCRYPTED AT REST (AES-256-GCM ciphertext). The app
  decrypts it automatically after your query runs, for display only. You may SELECT it, but NEVER
  filter or JOIN on it - each row's ciphertext was encrypted independently, so a WHERE/JOIN
  match against it (or against another row's copy of it) can never succeed. Including it in a
  SELECT list or a GROUP BY alongside a real key column (e.g. account_id) is fine.
- program_id (INTEGER): Program/product ID (0, 4, 21, 46, 99)
- available_balance (DECIMAL): Account balance (can be negative, zero, or extreme values) - already numeric, no CAST needed
- bank_code (VARCHAR, FOREIGN KEY): Reference to bank.bank_code

transaction:
- transaction_id (VARCHAR, PRIMARY KEY): Unique transaction identifier (UUID)
- account_id (VARCHAR, FOREIGN KEY): Reference to account.account_id
- transaction_date (TIMESTAMP): Transaction timestamp - already a real timestamp, no CAST needed
- transaction_type (VARCHAR): 'credit' or 'debit' (ONLY these two values)
- description (VARCHAR): Transaction description (can contain special chars, quotes, slashes)
- transaction_amount (DECIMAL): Amount (can be 0.00, micro amounts, or extreme values) - already numeric, no CAST needed
- transaction_reference_id (VARCHAR): Reference/receipt number, PLAINTEXT and directly searchable
  (often NULL, can be duplicated) - this is NOT the same column as utr_number, do not confuse them.
- utr_number (VARCHAR): Unique Transaction Reference - ENCRYPTED AT REST for most rows (some rows
  are legitimately plaintext or NULL). Same rule as account_number: SELECT it freely for display,
  but NEVER filter or JOIN on it (GROUP BY alongside a real key column is fine).

IMPORTANT RULES:
1. Add a DATE FILTER only when the user's question explicitly mentions a time period (last month, Q3, 2026, etc).
   If no time period is mentioned, return results across ALL dates in the dataset.
   transaction_date is a TIMESTAMP with a time-of-day component, not just a date - a whole-month
   or whole-day range MUST be written as `>= '2026-06-01' AND < '2026-07-01'`, never
   `BETWEEN '2026-06-01' AND '2026-06-30'` (BETWEEN's upper bound means midnight on the 30th,
   silently dropping every transaction later that same day).
   "Spend" means money going OUT - always filter transaction_type = 'debit' for spend/spending
   questions, never sum both credit and debit together.
2. JOIN tables only when necessary:
   - To get bank names: JOIN bank ON account.bank_code = bank.bank_code
   - To get account details: JOIN account ON transaction.account_id = account.account_id
   - Never JOIN unnecessarily - keep queries simple.
3. Use SUM(), COUNT(), AVG(), MIN(), MAX() for aggregations.
4. Filter transaction_type ONLY using exact values: 'credit' or 'debit'
5. A missing reference/UTR is a real SQL NULL - check with "IS NULL" / "IS NOT NULL", never "= ''"
6. Return meaningful column names using AS aliases
7. All numeric and date columns are already properly typed (DECIMAL / TIMESTAMP / INTEGER) -
   never wrap them in CAST(... AS DECIMAL); just compare/aggregate them directly.
8. account_number and utr_number are encrypted at rest - SELECT them freely, and IS NULL /
   IS NOT NULL checks are fine, but any other filter or JOIN condition on either one will be
   rejected before it even runs. If the user wants to look up a record BY account number or
   UTR, that isn't possible via SQL on encrypted columns - ask for a different identifier
   instead (account_id, transaction_id, bank + date range).
9. Never copy a literal value (account numbers, IDs, bank codes, dates, amounts) from the few-shot
   examples below into your query - they only demonstrate SQL structure/patterns. Only use filter
   values that literally appear in the CURRENT question. If the question names a bank but no
   specific account, filter on bank_code/bank_name only - do not add an account/date filter that
   wasn't mentioned.
10. Wrap SUM()/AVG() in COALESCE(..., 0) - e.g. COALESCE(SUM(transaction_amount), 0) - so a filter
    that matches zero rows returns 0, not NULL/blank.
11. "Sum"/"total" only applies to a numeric money column (available_balance, transaction_amount).
    "Sum of accounts", "total accounts", "how many accounts" etc. means counting rows/entities -
    use COUNT(*), never SUM(), when the thing being counted isn't itself a money amount.
12. Always think step-by-step before writing SQL.

OUTPUT FORMAT:
Return ONLY the SQL query, nothing else. No markdown, no explanation."""

# ============================================================================
# FEW-SHOT EXAMPLES FOR SQL GENERATION (TBX Schema)
# ============================================================================
SQL_EXAMPLES = [
    {
        "question": "What is the total amount of transactions from HDFC Bank?",
        "reasoning": "Need to: 1) JOIN account with bank to get bank names, 2) Filter by HDFC, 3) Sum transaction amounts",
        "sql": """SELECT
    b.bank_code,
    b.bank_name,
    COUNT(t.transaction_id) as transaction_count,
    SUM(t.transaction_amount) as total_amount
FROM account a
JOIN bank b ON a.bank_code = b.bank_code
JOIN transaction t ON a.account_id = t.account_id
WHERE b.bank_code = 'HDFC'
GROUP BY b.bank_code, b.bank_name"""
    },
    {
        "question": "Show me accounts with negative balances",
        "reasoning": "Need to: 1) Filter accounts where available_balance < 0, 2) Get bank name, 3) Show account details",
        "sql": """SELECT
    a.account_id,
    a.account_number,
    a.program_id,
    a.available_balance as balance,
    b.bank_name
FROM account a
JOIN bank b ON a.bank_code = b.bank_code
WHERE a.available_balance < 0
ORDER BY a.available_balance ASC"""
    },
    {
        "question": "How many credit vs debit transactions are there?",
        "reasoning": "Need to: 1) Group by transaction_type, 2) Count transactions, 3) Sum amounts for each type",
        "sql": """SELECT
    t.transaction_type,
    COUNT(t.transaction_id) as transaction_count,
    SUM(t.transaction_amount) as total_amount,
    AVG(t.transaction_amount) as avg_amount
FROM transaction t
GROUP BY t.transaction_type"""
    },
    {
        "question": "Which accounts have zero available balance?",
        "reasoning": "Need to: 1) Filter accounts where available_balance = 0, 2) Get associated transactions, 3) Show account details",
        "sql": """SELECT
    a.account_id,
    a.account_number,
    a.program_id,
    COUNT(t.transaction_id) as transaction_count,
    b.bank_name
FROM account a
LEFT JOIN transaction t ON a.account_id = t.account_id
JOIN bank b ON a.bank_code = b.bank_code
WHERE a.available_balance = 0
GROUP BY a.account_id, a.account_number, a.program_id, b.bank_name"""
    },
    {
        "question": "Show transactions with missing UTR or reference ID",
        "reasoning": "Need to: 1) Filter transactions where utr_number IS NULL OR transaction_reference_id IS NULL, 2) Get account/bank info, 3) Count how many",
        "sql": """SELECT
    t.transaction_id,
    t.account_id,
    t.transaction_date,
    t.transaction_type,
    t.transaction_amount as amount,
    t.description,
    CASE WHEN t.utr_number IS NULL THEN 'Missing UTR' ELSE 'Has UTR' END as utr_status,
    CASE WHEN t.transaction_reference_id IS NULL THEN 'Missing Ref' ELSE 'Has Ref' END as ref_status
FROM transaction t
WHERE t.utr_number IS NULL OR t.transaction_reference_id IS NULL
LIMIT 20"""
    },
    {
        "question": "What is the average transaction amount by account?",
        "reasoning": "Need to: 1) Group by account, 2) Calculate average amount, 3) Join to get bank/account details, 4) Order by average",
        "sql": """SELECT
    a.account_id,
    a.account_number,
    b.bank_name,
    COUNT(t.transaction_id) as transaction_count,
    AVG(t.transaction_amount) as avg_amount,
    MIN(t.transaction_amount) as min_amount,
    MAX(t.transaction_amount) as max_amount
FROM account a
LEFT JOIN transaction t ON a.account_id = t.account_id
JOIN bank b ON a.bank_code = b.bank_code
GROUP BY a.account_id, a.account_number, b.bank_name
ORDER BY avg_amount DESC"""
    },
    {
        "question": "How much did we spend in June 2026?",
        "reasoning": (
            "'Spend' means money going out - filter transaction_type = 'debit', never sum both "
            "credit and debit. transaction_date is a TIMESTAMP, so a whole-month range must use "
            "a half-open bound (>= start of month AND < start of NEXT month) - BETWEEN with a "
            "'2026-06-30' upper bound would silently drop every transaction later that same day."
        ),
        "sql": """SELECT SUM(transaction_amount) as total_spent
FROM transaction
WHERE transaction_type = 'debit'
    AND transaction_date >= '2026-06-01'
    AND transaction_date < '2026-07-01'"""
    },
    {
        "question": "For each bank, show average account balance and total transaction volume",
        "reasoning": (
            "Need TWO different aggregates from TWO different tables: AVG(available_balance) is "
            "per-account (from account), SUM(transaction_amount) is per-transaction (from "
            "transaction). Joining all three tables in one GROUP BY would fan out the account "
            "rows once per matching transaction, corrupting the account-side average. Compute "
            "each aggregate in its own subquery grouped by bank_code, then join the two results."
        ),
        "sql": """SELECT
    b.bank_code,
    b.bank_name,
    acct.avg_balance,
    txn.total_volume
FROM bank b
LEFT JOIN (
    SELECT bank_code, AVG(available_balance) as avg_balance
    FROM account
    GROUP BY bank_code
) acct ON b.bank_code = acct.bank_code
LEFT JOIN (
    SELECT a.bank_code, SUM(t.transaction_amount) as total_volume
    FROM account a
    JOIN transaction t ON a.account_id = t.account_id
    GROUP BY a.bank_code
) txn ON b.bank_code = txn.bank_code"""
    },
    {
        "question": "Find micro transactions (0.01 or less) and show their distribution by type",
        "reasoning": (
            "The threshold is explicit in the question (0.01), not 0 - use that exact boundary, "
            "not < 0 or = 0. Group by transaction_type and the amount itself to show the "
            "distribution, not just a single total."
        ),
        "sql": """SELECT
    transaction_type,
    transaction_amount,
    COUNT(*) as count
FROM transaction
WHERE transaction_amount <= 0.01
GROUP BY transaction_type, transaction_amount
ORDER BY transaction_type, transaction_amount"""
    },
    {
        "question": "What is the longest gap between consecutive transactions for each account?",
        "reasoning": (
            "'Gap between consecutive transactions' means the difference between each "
            "transaction and the one right before it for the SAME account, ordered by date - "
            "not simply the span between the first and last transaction. Use LAG() OVER "
            "(PARTITION BY account_id ORDER BY transaction_date) to get each transaction's "
            "previous transaction_date, compute the per-row gap, then take MAX per account. "
            "Keep this as ONE nested SELECT, not a separate WITH clause - a two-statement query "
            "is more likely to come out with a missing keyword or an unbalanced parenthesis."
        ),
        "sql": """SELECT account_id, MAX(gap) as longest_gap
FROM (
    SELECT
        account_id,
        transaction_date - LAG(transaction_date) OVER (
            PARTITION BY account_id ORDER BY transaction_date
        ) as gap
    FROM transaction
) sub
WHERE gap IS NOT NULL
GROUP BY account_id
ORDER BY longest_gap DESC"""
    },
    {
        "question": "For each bank, show the account number of the account with the highest available balance",
        "reasoning": (
            "This needs the account_number FROM THE SAME ROW as the max balance, not just "
            "'the highest balance' and 'some account_number' computed independently -  "
            "MAX(available_balance) and MAX(account_number) in the same GROUP BY are two "
            "unrelated aggregates and can silently pair values from two different accounts. "
            "Use ROW_NUMBER() OVER (PARTITION BY bank_code ORDER BY available_balance DESC) to "
            "rank accounts within each bank, then keep only rank 1 - that keeps every selected "
            "column tied to the correct single row."
        ),
        "sql": """SELECT bank_code, account_number, available_balance
FROM (
    SELECT
        bank_code,
        account_number,
        available_balance,
        ROW_NUMBER() OVER (PARTITION BY bank_code ORDER BY available_balance DESC) as rn
    FROM account
) ranked
WHERE rn = 1"""
    },
    {
        "question": "What is the total available balance for HDFC accounts?",
        "reasoning": (
            "The question names a bank (HDFC) but no specific account, so filter on bank_code "
            "only - do not add an account filter. 'Total' means SUM(), not a bare column "
            "selection. Wrap in COALESCE so a zero-match filter returns 0, not NULL."
        ),
        "sql": """SELECT
    COALESCE(SUM(a.available_balance), 0) as total_available_balance
FROM account a
JOIN bank b ON a.bank_code = b.bank_code
WHERE b.bank_code = 'HDFC'"""
    },
    {
        "question": "What is the sum of accounts for SBI?",
        "reasoning": (
            "'Sum of accounts' means counting how many account rows exist, not summing a money "
            "column - accounts don't have a 'sum' value. 'SBI' maps to bank_code SBIN per the "
            "known bank mapping (not 'SBI'). Use COUNT(*), not SUM()."
        ),
        "sql": """SELECT
    COUNT(*) as total_accounts
FROM account a
JOIN bank b ON a.bank_code = b.bank_code
WHERE b.bank_code = 'SBIN'"""
    }
]

# ============================================================================
# SQL REPAIR PROMPT (execution-feedback self-repair)
# One bounded retry: feed the real DB error back instead of asking the model to
# blindly "review" SQL with no signal to react to.
# ============================================================================
SQL_REPAIR_PROMPT_TEMPLATE = """This SQL query failed when run against the real database:

{sql}

Database error:
{error}

Fix the query so it runs successfully and still answers the original question: "{question}"
Common causes: a bank_code that isn't one of HDFC, ICIC, SBIN, UTIB, KKBK, CNRB, UBIN, AUBL,
TMBL, RATN (e.g. "SBI" should be "SBIN", "AXIS" should be "UTIB"); a non-aggregated column
missing from GROUP BY; SUM()/AVG() not wrapped in COALESCE(..., 0); or a wrong table alias.

Return ONLY the corrected SQL query, nothing else. No markdown, no explanation."""

# ============================================================================
# CLASSIFICATION PROMPT (Determine query type and confidence)
# ============================================================================
CLASSIFICATION_PROMPT = """{history_context}{entity_context}DATABASE SCHEMA (TBX Finance Assistant - for reference only, do not write SQL here):

bank:
- bank_code (VARCHAR, PRIMARY KEY): Bank code (e.g., HDFC, ICIC, SBIN, UTIB)
- bank_name (VARCHAR): Full bank name

account:
- account_id (VARCHAR, PRIMARY KEY): Unique account ID (UUID)
- entity_id (VARCHAR): Entity/customer ID (UUID)
- account_number (VARCHAR): Account number - ENCRYPTED AT REST, cannot be searched/filtered by SQL
- program_id (INTEGER): Program ID (0, 4, 21, 46, 99)
- available_balance (DECIMAL): Current balance (can be negative/zero/extreme)
- bank_code (VARCHAR, FOREIGN KEY): Reference to bank.bank_code

transaction:
- transaction_id (VARCHAR, PRIMARY KEY): Unique transaction ID (UUID)
- account_id (VARCHAR, FOREIGN KEY): Reference to account.account_id
- transaction_date (TIMESTAMP): Transaction timestamp
- transaction_type (VARCHAR): 'credit' or 'debit' (ONLY these values)
- description (VARCHAR): Transaction description
- transaction_amount (DECIMAL): Amount (can be 0.00, extreme values, etc.)
- transaction_reference_id (VARCHAR): Reference/receipt number, PLAINTEXT (often NULL, can be duplicated)
- utr_number (VARCHAR): UTR - ENCRYPTED AT REST for most rows, cannot be searched/filtered by SQL

Analyze this question about financial data:
"{question}"

Extract:
1. intent: What type of query? (account_balances, transaction_analysis, bank_summary, specific_account, transaction_search, other)
2. entities: Which accounts/banks/programs/amounts mentioned?
3. filters: What conditions? (date range, bank_code, account_id, transaction_type, balance range, missing_fields, etc.)
4. confidence: How clear is the question? (high/medium/low)
5. clarification_needed: What additional info would help? (if any)

The dataset spans multiple years (2023-2026). If a date is ambiguous, ask for clarification.
If the question can be answered directly (e.g., "show negative balance accounts"), confidence is high.

Respond in JSON format:
{{
    "intent": "...",
    "entities": {{}},
    "filters": {{}},
    "confidence_score": 0.0-1.0,
    "clarification_questions": []
}}"""

# vLLM enforces this via guided decoding on the OpenAI-compatible response_format param
# (confirmed against the deployed endpoint - see backend/langgraph_flow.py's call_llm),
# so classify_query_node gets guaranteed-valid JSON instead of hunting for braces in free
# text. Bedrock (fallback path) ignores response_format and relies on the prompt text above.
CLASSIFICATION_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "query_classification",
        "schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "entities": {"type": "object"},
                "filters": {"type": "object"},
                "confidence_score": {"type": "number"},
                "clarification_questions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["intent", "entities", "filters", "confidence_score", "clarification_questions"],
        },
    },
}

# ============================================================================
# CLARIFICATION PROMPT (Ask user for missing info)
# ============================================================================
CLARIFICATION_PROMPT_TEMPLATE = """I need clarification to answer your question accurately:

Your question: "{question}"

{clarification_questions}

Please provide the missing details, then I can give you an accurate answer."""

# ============================================================================
# RESPONSE FORMATTING PROMPT
# ============================================================================
RESPONSE_FORMATTING_PROMPT = """You are formatting a financial analysis response.

Question: {question}
Query Results: {results}
Confidence Score: {confidence_score}

Guidelines:
1. Start with a clear, concise answer (1-2 sentences)
2. Include key numbers from results
3. Mention the confidence level if < 0.8
4. If anomalies detected, flag them with explanation
5. End with data summary (how many records, date range, etc.)

Format:
**Answer**: [Main answer]
**Details**: [Key findings]
**Confidence**: [High/Medium/Low - explain if low]
**Data Summary**: [Records analyzed, date range, filters applied]
{anomalies_section}"""

# ============================================================================
# ANOMALY EXPLANATION PROMPT
# ============================================================================
ANOMALY_EXPLANATION_PROMPT = """Explain why these transactions are anomalous:

Vendor: {vendor_name}
Historical Average: ${avg_amount:.2f}
Current Transaction: ${current_amount:.2f}
Multiple of Average: {multiple}x

Provide a brief, business-friendly explanation of why this stands out."""

# ============================================================================
# CONFIDENCE SCORING COMPONENTS
# ============================================================================
CONFIDENCE_COMPONENTS = {
    "temperature": "Model uncertainty (lower = higher confidence)",
    "data_completeness": "Percentage of requested data available",
    "query_clarity": "How unambiguous was the user's question",
    "result_reliability": "How confident we are in the results"
}

_STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "for", "in", "on", "by", "to", "and", "or", "what",
    "which", "show", "me", "how", "many", "much", "with", "do", "we", "did", "list", "find",
    "get", "there", "all", "each", "per",
}


def _tokenize(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9_]+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _select_examples(user_question: str, k: int = 5) -> List[Dict[str, str]]:
    """Pick the k most relevant few-shot examples by keyword overlap (question + reasoning
    text, so domain vocabulary like "gap"/"consecutive"/"micro" is matchable) instead of always
    sending the full example bank - keeps the prompt focused for a small model as the example
    bank grows. No embeddings needed for a question set this scoped; ties keep original order.
    # ponytail: keyword overlap, add embedding similarity if the example bank grows much larger
    """
    q_tokens = _tokenize(user_question)
    scored = [
        (len(q_tokens & _tokenize(ex["question"] + " " + ex["reasoning"])), i, ex)
        for i, ex in enumerate(SQL_EXAMPLES)
    ]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [ex for _, _, ex in scored[:k]]


def _entity_scope_note(entity_id: Optional[str]) -> str:
    """A user-selected entity_id locks the conversation to that customer's accounts - pronouns
    like 'its'/'their'/'this account' then refer to it without asking for clarification."""
    if not entity_id:
        return ""
    return (
        f"The user has selected entity_id = '{entity_id}' in the UI. Treat pronouns like "
        f"'its'/'their'/'this account' as referring to accounts owned by this entity, and do "
        f"not ask for clarification on which account/entity - use entity_id = '{entity_id}' "
        f"instead.\n\n"
    )


def build_few_shot_prompt(user_question: str, history_context: str = "", entity_id: Optional[str] = None) -> str:
    """Build few-shot prompt with the most relevant examples, optionally grounded in prior turns
    and scoped to one entity_id (locked in the UI)."""
    examples_text = ""
    for i, example in enumerate(_select_examples(user_question), 1):
        examples_text += f"""
Example {i}:
Question: {example['question']}
Thinking: {example['reasoning']}
SQL: {example['sql']}
---
"""

    return f"""{SQL_GENERATION_SYSTEM_PROMPT}

{_entity_scope_note(entity_id)}{history_context}{examples_text}

Now, for this question:
{user_question}

Generate the SQL query:"""

def build_repair_prompt(sql: str, error: str, question: str) -> str:
    """Build the execution-feedback repair prompt: feed the real DB error back to the model"""
    return SQL_REPAIR_PROMPT_TEMPLATE.format(sql=sql, error=error, question=question)

def build_classification_prompt(user_question: str, history_context: str = "", entity_id: Optional[str] = None) -> str:
    """Build the query classification prompt, optionally grounded in prior conversation turns
    and scoped to one entity_id (locked in the UI)."""
    return CLASSIFICATION_PROMPT.format(
        question=user_question, history_context=history_context,
        entity_context=_entity_scope_note(entity_id),
    )

def build_response_prompt(question: str, results: str, confidence: float, 
                         anomalies: str = "") -> str:
    """Build response formatting prompt"""
    anomaly_section = f"\n**Anomalies Detected**:\n{anomalies}" if anomalies else ""
    
    return RESPONSE_FORMATTING_PROMPT.format(
        question=question,
        results=results,
        confidence_score=confidence,
        anomalies_section=anomaly_section
    )
