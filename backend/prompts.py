"""
LLM Prompts for TBX Finance Assistant
Includes few-shot examples, system prompts, and response formatting
TBX Schema: bank, account, transaction
"""

# ============================================================================
# SYSTEM PROMPT FOR SQL GENERATION
# ============================================================================
SQL_GENERATION_SYSTEM_PROMPT = """You are an expert SQL developer for TBX financial data analysis.
Your job is to convert natural language questions into precise SQL queries.

DATABASE SCHEMA (TBX Finance Assistant):
EXACT TABLE NAMES (use these EXACTLY as shown - singular, lowercase):
- bank (NOT "banks")
- account (NOT "accounts")
- transaction (NOT "transactions" - this is SINGULAR)

bank table:
- bank_code (VARCHAR, PRIMARY KEY): Bank identifier code (e.g., HDFC, ICIC, SBIN, UTIB)
- bank_name (VARCHAR): Canonical bank name in all-caps (e.g., HDFC BANK LIMITED)

KNOWN bank_code -> bank_name MAPPING (the ONLY banks that exist - do not invent others, and do NOT
guess a bank_code from abbreviation; several codes do NOT match the common short name, e.g. State
Bank of India / "SBI" is code SBIN, not "SBI"; Axis Bank is code UTIB, not "AXIS"):
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
When the user names a bank, look it up in this mapping and filter using the matching bank_code
(preferred, exact match) or `UPPER(b.bank_name) LIKE UPPER('%<key part of name>%')` if unsure.
Never filter using a bank_code you invented that isn't in this list.

account table:
- account_id (VARCHAR, PRIMARY KEY): Unique account identifier (UUID)
- entity_id (VARCHAR): Customer/entity that owns this account (UUID)
- account_number (VARCHAR): Account number (SENSITIVE - encrypted in database, automatically decrypted at runtime for display)
- program_id (VARCHAR): Program/product ID (0, 4, 21, 46, 99)
- available_balance (VARCHAR): Account balance (can be negative, zero, or extreme values)
- bank_code (VARCHAR, FOREIGN KEY): Reference to bank.bank_code

transaction table (SINGULAR - NOT "transactions"):
- transaction_id (VARCHAR, PRIMARY KEY): Unique transaction identifier (UUID)
- account_id (VARCHAR, FOREIGN KEY): Reference to account.account_id
- transaction_date (VARCHAR): Transaction timestamp in ISO 8601 format (YYYY-MM-DDTHH:MM:SS.microseconds). 
  IMPORTANT: When users ask about "transaction date" without specifying time, extract DATE only: CAST(transaction_date AS DATE) or DATE(transaction_date)
  Example: "What is the most common transaction date?" → GROUP BY CAST(transaction_date AS DATE), not the full timestamp
- transaction_type (VARCHAR): 'credit' or 'debit' (ONLY these two values)
- description (VARCHAR): Transaction description (can contain special chars, quotes, slashes)
- transaction_amount (VARCHAR): Amount (can be 0.00, micro amounts, or extreme values)
- transaction_reference_id (VARCHAR): Reference/receipt number (plaintext, directly searchable)
- utr_number (VARCHAR): UTR (SENSITIVE - encrypted in database, automatically decrypted at runtime for display)

CRITICAL TABLE NAME RULES:
1. The correct table name is "transaction" (SINGULAR). NEVER use "transactions" (plural).
2. Use FROM transaction, JOIN transaction, not FROM transactions or JOIN transactions
3. When the user asks "show me transactions" or "list all transactions", still use FROM transaction (singular)
4. When querying for transaction data, always use: FROM transaction (singular table name)

IMPORTANT RULES:
1. Add a DATE FILTER only when the user's question explicitly mentions a time period (last month, Q3, 2026, etc).
   If no time period is mentioned, return results across ALL dates in the dataset.
2. CRITICAL - DATE vs DATETIME: transaction_date contains full ISO 8601 datetime (YYYY-MM-DDTHH:MM:SS.microseconds).
   When users ask about "transaction date" or "dates" without mentioning time, extract DATE ONLY using CAST(transaction_date AS DATE).
   Example: "What is the most common transaction date?" → GROUP BY CAST(transaction_date AS DATE), NOT the full timestamp.
   This ensures grouping by calendar date, not by each unique datetime combination.
3. SENSITIVE COLUMN HANDLING - account_number and utr_number are encrypted in the database but WILL BE DECRYPTED AT RUNTIME:
   - You can query them directly: SELECT account_number FROM account WHERE ...
   - You can JOIN on account_number: JOIN account ON transaction.account_id = account.account_id
   - They will be decrypted automatically before being shown to the user
   - No special handling needed in SQL - just query normally
4. JOIN tables only when necessary:
   - To get bank names: JOIN bank ON account.bank_code = bank.bank_code
   - To get account details: JOIN account ON transaction.account_id = account.account_id
   - Never JOIN unnecessarily - keep queries simple.
5. Use SUM(), COUNT(), AVG(), MIN(), MAX() for aggregations.
6. Filter transaction_type ONLY using exact values: 'credit' or 'debit'
7. Handle NULL/empty fields gracefully (transaction_reference_id and utr_number are often empty)
8. When filtering by reference number or UTR, remember they can be NULL/empty strings ('')
9. Return meaningful column names using AS aliases
10. IMPORTANT: Cast numeric columns when needed: CAST(available_balance AS DECIMAL), CAST(transaction_amount AS DECIMAL)
11. IMPORTANT - account_id vs account_number: account_id is an internal UUID (e.g. 'acfbe204-7541-492c-a352-040aa984bedc') and is almost NEVER what a user types in a question. account_number is the numeric string a user actually refers to (e.g. '50200013729069'). If the user's question gives a numeric/digit-string account value, filter on account_number. Only filter on account_id if the value is a UUID (contains hyphens in the 8-4-4-4-12 pattern) or the user explicitly says "account ID".
12. Always think step-by-step before writing SQL.
13. CRITICAL - NEVER copy literal values (account numbers, IDs, bank codes, dates, amounts) from the
    examples below into your query. The examples only demonstrate SQL structure/patterns. Only use
    filter values that literally appear in the CURRENT user's question. If the question names a bank
    (e.g. "HDFC") but no specific account, filter on bank_code/bank_name only - do NOT add an
    account_number filter that wasn't mentioned. If the question says "sum"/"total", the query MUST
    use SUM(), not a bare column selection.
14. NULL-SAFE AGGREGATES: Always wrap SUM()/AVG() in COALESCE(..., 0) - e.g. COALESCE(SUM(CAST(x AS
    DECIMAL)), 0) - so a filter that matches zero rows returns 0 instead of NULL/blank.
15. "SUM"/"TOTAL" ONLY APPLIES TO NUMERIC COLUMNS (available_balance, transaction_amount). If the
    user asks for "sum of accounts", "sum of transactions", "total accounts", etc. (counting rows/
    entities, not a money amount), this means COUNT(*), NOT SUM(). Only use SUM() on the actual
    numeric money column being asked about.

OUTPUT FORMAT:
Return ONLY the SQL query, nothing else. No markdown, no explanation."""

# ============================================================================
# FEW-SHOT EXAMPLES FOR SQL GENERATION (TBX Schema)
# ============================================================================
SQL_EXAMPLES = [
    {
        "question": "What is the total amount of transactions from HDFC Bank?",
        "reasoning": "Need to: 1) JOIN account with bank to get bank names, 2) JOIN transaction (singular table!) to get transaction data, 3) Filter by HDFC, 4) Sum transaction amounts",
        "sql": """SELECT 
    b.bank_code,
    b.bank_name,
    COUNT(t.transaction_id) as transaction_count,
    SUM(CAST(t.transaction_amount AS DECIMAL)) as total_amount
FROM account a
JOIN bank b ON a.bank_code = b.bank_code
JOIN transaction t ON a.account_id = t.account_id
WHERE b.bank_code = 'HDFC'
GROUP BY b.bank_code, b.bank_name"""
    },
    {
        "question": "Show me all transactions",
        "reasoning": "User asks for 'transactions' (plural) but the table name is 'transaction' (singular). Always use FROM transaction, not FROM transactions",
        "sql": """SELECT 
    t.transaction_id,
    t.account_id,
    t.transaction_date,
    t.transaction_type,
    CAST(t.transaction_amount AS DECIMAL) as amount,
    t.description
FROM transaction t
LIMIT 100"""
    },
    {
        "question": "Show me accounts with negative balances",
        "reasoning": "Need to: 1) Filter accounts where available_balance < 0, 2) Get bank name, 3) Show account details",
        "sql": """SELECT 
    a.account_id,
    a.account_number,
    a.program_id,
    CAST(a.available_balance AS DECIMAL) as balance,
    b.bank_name
FROM account a
JOIN bank b ON a.bank_code = b.bank_code
WHERE CAST(a.available_balance AS DECIMAL) < 0
ORDER BY CAST(a.available_balance AS DECIMAL) ASC"""
    },
    {
        "question": "What's the available balance for account 50200013729069?",
        "reasoning": "The value '50200013729069' is a numeric digit-string, not a UUID, so it refers to account.account_number, NOT account.account_id. This literal number came from the question itself - never reuse it for a different question.",
        "sql": """SELECT 
    CAST(a.available_balance AS DECIMAL) as available_balance
FROM account a
WHERE a.account_number = '50200013729069'
LIMIT 1"""
    },
    {
        "question": "What is the total available balance for HDFC accounts?",
        "reasoning": "The question names a bank (HDFC) but no specific account, so filter on bank_code only - do NOT add an account_number filter. The question says 'total', so use SUM(), not a bare column selection. Wrap in COALESCE so a zero-match filter returns 0, not NULL.",
        "sql": """SELECT 
    COALESCE(SUM(CAST(a.available_balance AS DECIMAL)), 0) as total_available_balance
FROM account a
JOIN bank b ON a.bank_code = b.bank_code
WHERE b.bank_code = 'HDFC'"""
    },
    {
        "question": "What is the sum of accounts for SBI?",
        "reasoning": "'Sum of accounts' means counting how many account rows exist, not summing a money column - accounts don't have a 'sum' value. 'SBI' maps to bank_code SBIN per the known bank mapping (not 'SBI'). Use COUNT(*), not SUM().",
        "sql": """SELECT 
    COUNT(*) as total_accounts
FROM account a
JOIN bank b ON a.bank_code = b.bank_code
WHERE b.bank_code = 'SBIN'"""
    },
    {
        "question": "How many credit vs debit transactions are there?",
        "reasoning": "Need to: 1) Query from transaction table (SINGULAR), 2) Group by transaction_type, 3) Count and sum by type",
        "sql": """SELECT 
    t.transaction_type,
    COUNT(t.transaction_id) as transaction_count,
    SUM(CAST(t.transaction_amount AS DECIMAL)) as total_amount,
    AVG(CAST(t.transaction_amount AS DECIMAL)) as avg_amount
FROM transaction t
GROUP BY t.transaction_type"""
    },
    {
        "question": "Show me total transactions count",
        "reasoning": "User asks for 'transactions' but table is 'transaction' (singular). Use FROM transaction, not FROM transactions",
        "sql": """SELECT 
    COUNT(*) as total_transactions
FROM transaction"""
    },
    {
        "question": "Which accounts have zero available balance?",
        "reasoning": "Need to: 1) Filter accounts where available_balance = '0.00', 2) Get associated transactions from transaction table, 3) Show account details",
        "sql": """SELECT 
    a.account_id,
    a.account_number,
    a.program_id,
    COUNT(t.transaction_id) as transaction_count,
    b.bank_name
FROM account a
LEFT JOIN transaction t ON a.account_id = t.account_id
JOIN bank b ON a.bank_code = b.bank_code
WHERE a.available_balance = '0.00'
GROUP BY a.account_id, a.account_number, a.program_id, b.bank_name"""
    },
    {
        "question": "Show transactions with missing UTR or reference ID",
        "reasoning": "Need to: 1) Query from transaction table (SINGULAR), 2) Filter where utr_number is empty OR transaction_reference_id is empty, 3) Count how many",
        "sql": """SELECT 
    t.transaction_id,
    t.account_id,
    t.transaction_date,
    t.transaction_type,
    CAST(t.transaction_amount AS DECIMAL) as amount,
    t.description,
    CASE WHEN t.utr_number = '' THEN 'Missing UTR' ELSE 'Has UTR' END as utr_status,
    CASE WHEN t.transaction_reference_id = '' THEN 'Missing Ref' ELSE 'Has Ref' END as ref_status
FROM transaction t
WHERE t.utr_number = '' OR t.transaction_reference_id = ''
LIMIT 20"""
    },
    {
        "question": "What is the average transaction amount by account?",
        "reasoning": "Need to: 1) Query from transaction table (SINGULAR), 2) Group by account, 3) Calculate average amount, 4) Join to get bank/account details, 5) Order by average",
        "sql": """SELECT 
    a.account_id,
    a.account_number,
    b.bank_name,
    COUNT(t.transaction_id) as transaction_count,
    AVG(CAST(t.transaction_amount AS DECIMAL)) as avg_amount,
    MIN(CAST(t.transaction_amount AS DECIMAL)) as min_amount,
    MAX(CAST(t.transaction_amount AS DECIMAL)) as max_amount
FROM account a
LEFT JOIN transaction t ON a.account_id = t.account_id
JOIN bank b ON a.bank_code = b.bank_code
GROUP BY a.account_id, a.account_number, b.bank_name
ORDER BY avg_amount DESC"""
    },
    {
        "question": "What is the most common transaction date?",
        "reasoning": "The user asks about 'transaction date' without specifying time. transaction_date contains full ISO datetime. Extract DATE only using CAST(transaction_date AS DATE). Query from transaction (SINGULAR table)",
        "sql": """SELECT 
    CAST(transaction_date AS DATE) as transaction_date,
    COUNT(transaction_id) as transaction_count
FROM transaction
GROUP BY CAST(transaction_date AS DATE)
ORDER BY transaction_count DESC
LIMIT 10"""
    }
]

# ============================================================================
# PROMPT FOR CHAIN-OF-THOUGHT SQL GENERATION
# ============================================================================
COT_PROMPT_TEMPLATE = """Question: {question}

IMPORTANT: The tables are named: bank, account, transaction (all SINGULAR - NOT plural)

Think step-by-step:
1. What data do we need? (Which tables? Remember: bank, account, transaction - all singular)
2. What filters apply? (vendor, status - only add a date range if a time period is explicitly mentioned)
3. What calculations? (SUM, COUNT, AVG?)
4. How to join tables? (if needed)
5. What order/limit? (sorting, top results?)

CRITICAL REMINDER:
- Use FROM transaction (NOT FROM transactions)
- Use FROM account (NOT FROM accounts) 
- Use FROM bank (NOT FROM banks)
- Always use singular table names in all JOINs and WHERE clauses

Now write the SQL query based on this reasoning:"""

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
- account_number (VARCHAR): Account number (SENSITIVE - do not expose)
- program_id (VARCHAR): Program ID (0, 4, 21, 46, 99)
- available_balance (VARCHAR): Current balance (can be negative/zero/extreme)
- bank_code (VARCHAR, FOREIGN KEY): Reference to bank.bank_code

transaction:
- transaction_id (VARCHAR, PRIMARY KEY): Unique transaction ID (UUID)
- account_id (VARCHAR, FOREIGN KEY): Reference to account.account_id
- transaction_date (VARCHAR): Transaction timestamp (YYYY-MM-DD HH:MM:SS.microseconds)
- transaction_type (VARCHAR): 'credit' or 'debit' (ONLY these values)
- description (VARCHAR): Transaction description
- transaction_amount (VARCHAR): Amount (can be 0.00, extreme values, etc.)
- transaction_reference_id (VARCHAR): Reference/receipt number (often empty, can be duplicated)
- utr_number (VARCHAR): UTR (often empty, encrypted, or plaintext)

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
SQL_VALIDATION_PROMPT = """Review this SQL query for correctness:

{sql}

CRITICAL TABLE NAMES (must be singular):
- transaction (NOT transactions)
- account (NOT accounts)
- bank (NOT banks)

Check:
1. Table Names: All table names are SINGULAR (transaction, account, bank)? 
   - REJECT if using "transactions", "accounts", or "banks" (plural)
2. Syntax: Valid SQL?
3. Schema: All tables/columns exist?
4. Logic: Answers the question correctly?
5. Performance: Reasonable query structure?
6. Bank codes: Only these bank_code values exist: HDFC, ICIC, SBIN, UTIB, KKBK, CNRB, UBIN, AUBL,
   TMBL, RATN. Reject/fix any other bank_code literal (e.g. 'SBI' should be 'SBIN', 'AXIS' should be
   'UTIB').
7. Aggregates: SUM()/AVG() should be wrapped in COALESCE(..., 0) so zero matching rows return 0, not NULL.

If there are issues (especially pluralized table names), fix them and return corrected SQL.
If query is correct, return it as-is.

Return ONLY the SQL query (corrected if needed), nothing else. No markdown, no explanation."""

# ============================================================================
# REPAIR PROMPT (Fix a query that failed at execution time, using the DB error)
# ============================================================================
SQL_REPAIR_PROMPT = """This SQL query failed when executed against the database:

{sql}

Database error:
{error}

Fix the query so it executes successfully against the same schema (tables: bank, account,
transaction - all singular) while still answering the original question. Common causes:
non-aggregated columns missing from GROUP BY, wrong table alias for a column, or a
plural table name.

Return ONLY the corrected SQL query, nothing else. No markdown, no explanation."""

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

def build_few_shot_prompt(user_question: str, history_context: str = "", entity_id: str = None) -> str:
    """Build few-shot prompt with examples, optionally grounded in prior turns and scoped to one entity_id"""
    examples_text = ""
    for i, example in enumerate(SQL_EXAMPLES, 1):
        examples_text += f"""
Example {i}:
Question: {example['question']}
Thinking: {example['reasoning']}
SQL: {example['sql']}
---
"""
    
    entity_instruction = ""
    if entity_id:
        entity_instruction = f"""
MANDATORY FILTER: The user has selected entity_id = '{entity_id}' in the UI. The query MUST be restricted to
this entity only. If the query touches the account table (directly or via JOIN), add
WHERE account.entity_id = '{entity_id}' (or AND account.entity_id = '{entity_id}' if a WHERE clause already exists).
If querying the account table directly, filter on account.entity_id = '{entity_id}'. If querying transaction,
JOIN account ON transaction.account_id = account.account_id and filter on account.entity_id = '{entity_id}'.
"""

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
