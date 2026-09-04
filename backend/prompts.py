"""
LLM Prompts for Finance Assistant
Includes few-shot examples, system prompts, and response formatting
"""

# ============================================================================
# SYSTEM PROMPT FOR SQL GENERATION
# ============================================================================
SQL_GENERATION_SYSTEM_PROMPT = """You are an expert SQL developer for financial data analysis.
Your job is to convert natural language questions into precise SQL queries.

DATABASE SCHEMA:
- transactions: transaction_id, vendor_id, transaction_date, transaction_type, amount, currency, account_id, account_name, description, status, invoice_number, reference_number, notes
  Example row: TXN0000001, V00439, 2024-12-19, Payment, 700.42, USD, 1013, Service Revenue, "Transaction for V00439", Rejected, INV725850, REF52421, (null)
  transaction_type values: Payment, Invoice, Expense, Refund, Credit Memo
  status values: Pending, Completed, Rejected, Hold
- vendor_payouts: payout_id, vendor_id, payout_date, amount, currency, payment_method, status, reference_number
  Example row: PO0000001, V00342, 2025-07-23, 485.87, USD, Wire Transfer, Cancelled, CHECK545461
  status values: Pending, Completed, Cancelled
- reconciliation_status: transaction_id, reconciliation_status, matched_payout_id, reconciliation_date, last_reviewed, notes
  Example row: TXN0000001, Reconciled, PO0000128, 2024-03-24, (null), (null)
  reconciliation_status values: Reconciled, Unreconciled, Partially Reconciled, Pending Reconciliation
- chart_of_accounts: account_id, account_name, account_type, category
  Example row: 1000, Cash, Assets, Assets
- vendor_list: vendor_id, vendor_name, industry, country, status
  Example row: V00001, Pro Tech 509, Retail, Canada, Active
  status values: Active, Inactive, On Hold

IMPORTANT RULES:
1. Always use DATE FILTERS when user mentions time periods (last month, Q3, year-to-date, etc.)
2. JOIN tables only when necessary - keep queries simple
3. Use SUM(), COUNT(), AVG() for aggregations
4. Filter by reconciliation_status when asking about unreconciled/reconciled transactions
5. Return meaningful column names using AS aliases
6. Date format in database: YYYY-MM-DD
7. When user says "last month", assume current month is December 2025, so "last month" = November 2025
8. Always think step-by-step before writing SQL

OUTPUT FORMAT:
Return ONLY the SQL query, nothing else. No markdown, no explanation."""

# ============================================================================
# FEW-SHOT EXAMPLES FOR SQL GENERATION
# ============================================================================
SQL_EXAMPLES = [
    {
        "question": "How much did we spend on vendor V00100 last month?",
        "reasoning": "Need to: 1) Filter by vendor V00100, 2) Filter by last month (November 2025), 3) Sum the amounts",
        "sql": """SELECT 
    vendor_id,
    SUM(amount) as total_spent,
    COUNT(*) as transaction_count,
    DATE_TRUNC('month', transaction_date) as month
FROM transactions
WHERE vendor_id = 'V00100'
    AND transaction_date >= '2025-11-01' 
    AND transaction_date < '2025-12-01'
GROUP BY vendor_id, DATE_TRUNC('month', transaction_date)"""
    },
    {
        "question": "Which transactions are still unreconciled?",
        "reasoning": "Need to: 1) Join transactions with reconciliation_status, 2) Filter where status is 'Unreconciled' or 'Pending Reconciliation' (not yet fully reconciled), 3) Return transaction details",
        "sql": """SELECT 
    t.transaction_id,
    t.vendor_id,
    t.transaction_date,
    t.amount,
    r.reconciliation_status,
    r.notes
FROM transactions t
LEFT JOIN reconciliation_status r ON t.transaction_id = r.transaction_id
WHERE r.reconciliation_status IN ('Unreconciled', 'Pending Reconciliation')
ORDER BY t.transaction_date DESC
LIMIT 100"""
    },
    {
        "question": "Show spending by vendor for Q3 2024",
        "reasoning": "Need to: 1) Filter Q3 2024 (July-Sept), 2) Group by vendor, 3) Sum amounts, 4) Join with vendor names",
        "sql": """SELECT 
    v.vendor_name,
    t.vendor_id,
    SUM(t.amount) as total_spent,
    COUNT(*) as transaction_count,
    AVG(t.amount) as avg_transaction
FROM transactions t
JOIN vendor_list v ON t.vendor_id = v.vendor_id
WHERE transaction_date >= '2024-07-01' 
    AND transaction_date < '2024-10-01'
GROUP BY t.vendor_id, v.vendor_name
ORDER BY total_spent DESC"""
    },
    {
        "question": "What are our highest-value payouts?",
        "reasoning": "Need to: 1) Get payout amounts, 2) Sort descending, 3) Limit to top results, 4) Include vendor name",
        "sql": """SELECT 
    p.payout_id,
    v.vendor_name,
    p.amount,
    p.payout_date,
    p.payment_method,
    p.status
FROM vendor_payouts p
JOIN vendor_list v ON p.vendor_id = v.vendor_id
ORDER BY p.amount DESC
LIMIT 20"""
    },
    {
        "question": "How much is outstanding from vendor ABC?",
        "reasoning": "Need to: 1) Find vendor by name, 2) Get unreconciled transactions for that vendor, 3) Sum amounts",
        "sql": """SELECT 
    t.vendor_id,
    v.vendor_name,
    SUM(t.amount) as outstanding_amount,
    COUNT(*) as transaction_count
FROM transactions t
JOIN vendor_list v ON t.vendor_id = v.vendor_id
LEFT JOIN reconciliation_status r ON t.transaction_id = r.transaction_id
WHERE LOWER(v.vendor_name) LIKE LOWER('%ABC%')
    AND (r.reconciliation_status IN ('Unreconciled', 'Pending Reconciliation') OR r.reconciliation_status IS NULL)
GROUP BY t.vendor_id, v.vendor_name"""
    }
]

# ============================================================================
# PROMPT FOR CHAIN-OF-THOUGHT SQL GENERATION
# ============================================================================
COT_PROMPT_TEMPLATE = """Question: {question}

Think step-by-step:
1. What data do we need? (Which tables?)
2. What filters apply? (vendor, date range, status?)
3. What calculations? (SUM, COUNT, AVG?)
4. How to join tables? (if needed)
5. What order/limit? (sorting, top results?)

Now write the SQL query based on this reasoning:"""

# ============================================================================
# CLASSIFICATION PROMPT (Determine query type and confidence)
# ============================================================================
CLASSIFICATION_PROMPT = """{history_context}Analyze this question about financial data:
"{question}"

Extract:
1. intent: What type of query? (vendor_spend, reconciliation_status, payouts, comparisons, other)
2. entities: Which vendors/accounts/time periods mentioned?
3. filters: What conditions? (date range, status, vendor, amount, etc.)
4. confidence: How clear is the question? (high/medium/low)
5. clarification_needed: What additional info would help? (if any)

If the previous conversation above answers or narrows this question (e.g. "what about last month"
following an earlier vendor question), use it to resolve entities/filters and raise confidence.

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
# VALIDATION PROMPT (Validate SQL correctness)
# ============================================================================
SQL_VALIDATION_PROMPT = """Review this SQL query for correctness:

{sql}

Check:
1. Syntax: Valid SQL?
2. Schema: All tables/columns exist?
3. Logic: Answers the question correctly?
4. Performance: Reasonable query structure?

If there are issues, fix them and return corrected SQL.
If query is correct, return it as-is.

Return ONLY the SQL query (corrected if needed), nothing else."""

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

def build_few_shot_prompt(user_question: str, history_context: str = "") -> str:
    """Build few-shot prompt with examples, optionally grounded in prior turns"""
    examples_text = ""
    for i, example in enumerate(SQL_EXAMPLES, 1):
        examples_text += f"""
Example {i}:
Question: {example['question']}
Thinking: {example['reasoning']}
SQL: {example['sql']}
---
"""
    
    return f"""{SQL_GENERATION_SYSTEM_PROMPT}

{history_context}{examples_text}

Now, for this question:
{user_question}

Generate the SQL query:"""

def build_cot_prompt(user_question: str, history_context: str = "") -> str:
    """Build chain-of-thought prompt, optionally grounded in prior turns"""
    return f"{history_context}{COT_PROMPT_TEMPLATE.format(question=user_question)}"

def build_classification_prompt(user_question: str, history_context: str = "") -> str:
    """Build the query classification prompt, optionally grounded in prior conversation turns"""
    return CLASSIFICATION_PROMPT.format(question=user_question, history_context=history_context)

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
