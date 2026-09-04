"""
Benchmarking Suite for TBX Finance Assistant
Test different Qwen models against diverse question sets
"""

import json
import time
import logging
import re
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
import statistics
import os
from dotenv import load_dotenv

import boto3
import duckdb

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# PS-compliant local model (genuinely 1.5B params) served via Ollama - the DEFAULT
LOCAL_MODEL_ALIASES = {"qwen2.5-coder-1.5b"}
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "qwen2.5-coder:1.5b")

_DANGEROUS_SQL = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|ATTACH|COPY|PRAGMA)\b",
    re.IGNORECASE,
)


def extract_sql(response_text: str) -> str:
    """Best-effort extraction of a single SELECT statement from raw LLM output."""
    fence_match = re.search(r"```(?:sql)?\s*(.*?)```", response_text, re.IGNORECASE | re.DOTALL)
    candidate = fence_match.group(1) if fence_match else response_text

    select_match = re.search(r"\bselect\b", candidate, re.IGNORECASE)
    if not select_match:
        return ""
    candidate = candidate[select_match.start():]

    semi_idx = candidate.find(";")
    if semi_idx != -1:
        candidate = candidate[:semi_idx]

    return candidate.strip()


def is_sql_safe(sql: str) -> bool:
    """Read-only guard: must be a SELECT and contain no mutating/DDL keywords."""
    return bool(sql) and sql.strip().lower().startswith("select") and not _DANGEROUS_SQL.search(sql)


def build_benchmark_db() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with read-only views over the real dataset for execution scoring."""
    con = duckdb.connect(database=":memory:")
    for table in ["transactions", "vendor_payouts", "reconciliation_status", "chart_of_accounts", "vendor_list"]:
        csv_path = DATA_DIR / f"{table}.csv"
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_csv_auto('{csv_path.as_posix()}')")
    return con

# System prompt reused from backend/prompts.py so the benchmark reflects real grounding behavior
SQL_SYSTEM_PROMPT = """You are an expert SQL developer for financial data analysis.
Convert natural language questions into precise DuckDB SQL queries.

DATABASE SCHEMA:
- transactions: transaction_id, vendor_id, transaction_date, transaction_type (Payment, Invoice, Expense, Refund, Credit Memo), amount, currency, account_id, account_name, status (Pending, Completed, Rejected, Hold), invoice_number, reference_number, notes
- vendor_payouts: payout_id, vendor_id, payout_date, amount, currency, payment_method, status (Pending, Completed, Cancelled), reference_number
- reconciliation_status: transaction_id, reconciliation_status (Reconciled, Partially Reconciled, Unreconciled, Pending Reconciliation), matched_payout_id, reconciliation_date, last_reviewed, notes
- chart_of_accounts: account_id, account_name, account_type (Assets, Liabilities, Revenue, Expense), category
- vendor_list: vendor_id, vendor_name, industry, country, status (Active, Inactive, On Hold)

RULES:
1. Use date filters whenever the question mentions a time period.
2. Join tables only when necessary.
3. Use SUM/COUNT/AVG/STDDEV for aggregations.
4. Assume "today" is 2025-12-01 for relative date phrases like "last month".
5. Enum-like columns (transaction_type, status, reconciliation_status) must be filtered using
   the exact values listed in the schema above (case-sensitive) - never invent or guess values.
6. When the question implies "spending" or "payments" without naming a specific type, do NOT
   add a transaction_type/status filter unless the question explicitly asks to narrow it down.
7. Always include the relevant *_id column (e.g. vendor_id) in the SELECT list alongside any
   human-readable name, so results can be uniquely identified.
8. "Unreconciled"/"outstanding" means reconciliation_status IN ('Unreconciled', 'Pending Reconciliation') -
   not yet fully reconciled. "Reconciled" alone means status = 'Reconciled' only (excludes 'Partially Reconciled').

OUTPUT FORMAT: Return ONLY the SQL query, no markdown fences, no explanation."""

# System prompt for turn 1 of multiturn questions: ambiguous requests should be
# clarified before any SQL is written, instead of guessing at undefined thresholds/periods.
CLARIFYING_SYSTEM_PROMPT = SQL_SYSTEM_PROMPT + """

CLARIFICATION RULE: If the question relies on an undefined threshold, time period, or
metric definition that would change the SQL depending on interpretation (e.g. "high
variance", "outstanding", "recent"), do NOT write SQL yet. Instead, ask ONE short
clarifying question to resolve the ambiguity. If the question is already unambiguous,
answer normally per the OUTPUT FORMAT above."""

# ============================================================================
# TEST QUESTION SETS
# ============================================================================

TEST_QUESTIONS = {
    "easy": [
        {
            "id": "easy_001",
            "question": "How much did we spend on vendor V00100 in November 2025?",
            "expected_contains": ["V00100", "November", "2025"],
            "complexity": "easy",
            "type": "vendor_spend",
            "answer_type": "scalar",
            "reference_sql": "SELECT SUM(amount) AS total FROM transactions WHERE vendor_id = 'V00100' AND transaction_date >= '2025-11-01' AND transaction_date < '2025-12-01'"
        },
        {
            "id": "easy_002",
            "question": "Which transactions are unreconciled?",
            "expected_contains": ["unreconciled", "reconciliation_status"],
            "complexity": "easy",
            "type": "reconciliation_status",
            "answer_type": "list",
            "id_column": "transaction_id",
            "reference_sql": "SELECT transaction_id FROM reconciliation_status WHERE reconciliation_status IN ('Unreconciled', 'Pending Reconciliation')"
        },
        {
            "id": "easy_003",
            "question": "Show me all vendor payouts from October 2024",
            "expected_contains": ["October", "2024", "payouts"],
            "complexity": "easy",
            "type": "payouts",
            "answer_type": "list",
            "id_column": "payout_id",
            "reference_sql": "SELECT payout_id FROM vendor_payouts WHERE payout_date >= '2024-10-01' AND payout_date < '2024-11-01'"
        },
        {
            "id": "easy_004",
            "question": "What's the total amount spent last month?",
            "expected_contains": ["SUM", "November", "2025"],
            "complexity": "easy",
            "type": "total_spend",
            "answer_type": "scalar",
            "reference_sql": "SELECT SUM(amount) AS total FROM transactions WHERE transaction_date >= '2025-11-01' AND transaction_date < '2025-12-01'"
        },
        {
            "id": "easy_005",
            "question": "How many transactions do we have?",
            "expected_contains": ["COUNT", "transactions"],
            "complexity": "easy",
            "type": "count",
            "answer_type": "scalar",
            "reference_sql": "SELECT COUNT(*) AS cnt FROM transactions"
        }
    ],
    
    "moderate": [
        {
            "id": "mod_001",
            "question": "Show spending by vendor for Q3 2024 with totals",
            "expected_contains": ["GROUP BY", "vendor", "2024-07", "2024-10"],
            "complexity": "moderate",
            "type": "vendor_breakdown",
            "answer_type": "list",
            "id_column": "vendor_id",
            "reference_sql": "SELECT vendor_id, SUM(amount) AS total FROM transactions WHERE transaction_date >= '2024-07-01' AND transaction_date < '2024-10-01' GROUP BY vendor_id"
        },
        {
            "id": "mod_002",
            "question": "Which vendors had more than $50,000 in payments last year?",
            "expected_contains": ["vendor", "payout", "2024", "50000"],
            "complexity": "moderate",
            "type": "vendor_threshold",
            "answer_type": "list",
            "id_column": "vendor_id",
            "reference_sql": "SELECT vendor_id, SUM(amount) AS total FROM vendor_payouts WHERE payout_date >= '2024-01-01' AND payout_date < '2025-01-01' GROUP BY vendor_id HAVING SUM(amount) > 50000"
        },
        {
            "id": "mod_003",
            "question": "How much is still outstanding from unreconciled transactions?",
            "expected_contains": ["unreconciled", "SUM", "amount"],
            "complexity": "moderate",
            "type": "outstanding",
            "answer_type": "scalar",
            "reference_sql": "SELECT SUM(t.amount) AS total FROM transactions t JOIN reconciliation_status r ON t.transaction_id = r.transaction_id WHERE r.reconciliation_status IN ('Unreconciled', 'Pending Reconciliation')"
        },
        {
            "id": "mod_004",
            "question": "Show the top 10 largest transactions across all vendors",
            "expected_contains": ["ORDER BY", "amount", "DESC", "LIMIT 10"],
            "complexity": "moderate",
            "type": "top_transactions",
            "answer_type": "list",
            "id_column": "transaction_id",
            "reference_sql": "SELECT transaction_id, amount FROM transactions ORDER BY amount DESC LIMIT 10"
        },
        {
            "id": "mod_005",
            "question": "Compare spending between Q3 and Q4 2024",
            "expected_contains": ["2024-07", "2024-10", "2024-10", "2025-01"],
            "complexity": "moderate",
            "type": "period_comparison",
            "answer_type": "keyed_rows",
            "reference_sql": "SELECT 'Q3' AS quarter, SUM(amount) AS total FROM transactions WHERE transaction_date >= '2024-07-01' AND transaction_date < '2024-10-01' UNION ALL SELECT 'Q4' AS quarter, SUM(amount) AS total FROM transactions WHERE transaction_date >= '2024-10-01' AND transaction_date < '2025-01-01'"
        }
    ],
    
    "complex": [
        {
            "id": "complex_001",
            "question": "For each vendor with high variance in transaction amounts (indicating possible billing errors), show their average amount and count of transactions",
            "expected_contains": ["GROUP BY", "vendor", "STDDEV", "AVG", "COUNT"],
            "complexity": "complex",
            "type": "statistical_analysis",
            "answer_type": "list",
            "id_column": "vendor_id",
            "multiturn": True,
            "clarifying_reply": "Use a standard deviation greater than 500 as the threshold for 'high variance'.",
            "reference_sql": "SELECT vendor_id, AVG(amount) AS avg_amount, COUNT(*) AS txn_count FROM transactions GROUP BY vendor_id HAVING STDDEV(amount) > 500"
        },
        {
            "id": "complex_002",
            "question": "Which vendors have unreconciled transactions that don't have matching payouts, and what's the total outstanding amount?",
            "expected_contains": ["LEFT JOIN", "unreconciled", "matched_payout_id", "NULL"],
            "complexity": "complex",
            "type": "reconciliation_gap_analysis",
            "answer_type": "list",
            "id_column": "vendor_id",
            "multiturn": True,
            "clarifying_reply": "Include all transaction types and all dates, no additional filtering.",
            "reference_sql": "SELECT t.vendor_id, SUM(t.amount) AS outstanding FROM transactions t JOIN reconciliation_status r ON t.transaction_id = r.transaction_id WHERE r.reconciliation_status IN ('Unreconciled', 'Pending Reconciliation') AND r.matched_payout_id IS NULL GROUP BY t.vendor_id"
        },
        {
            "id": "complex_003",
            "question": "Identify vendors whose last transaction was more than 6 months ago and list their outstanding unreconciled amounts",
            "expected_contains": ["DATE", "MAX", "unreconciled", "2025-03"],
            "complexity": "complex",
            "type": "dormant_vendors",
            "answer_type": "list",
            "id_column": "vendor_id",
            "multiturn": True,
            "clarifying_reply": "Assume today is 2025-12-01 and use exactly 6 calendar months, so 'dormant' means their last transaction was before 2025-06-01.",
            "reference_sql": "SELECT t.vendor_id, SUM(t.amount) AS outstanding FROM transactions t JOIN reconciliation_status r ON t.transaction_id = r.transaction_id WHERE r.reconciliation_status IN ('Unreconciled', 'Pending Reconciliation') AND t.vendor_id IN (SELECT vendor_id FROM transactions GROUP BY vendor_id HAVING MAX(transaction_date) < '2025-06-01') GROUP BY t.vendor_id"
        },
        {
            "id": "complex_004",
            "question": "Show a breakdown of reconciliation status by month for 2024, including counts and percentages",
            "expected_contains": ["DATE_TRUNC", "reconciliation_status", "COUNT", "CASE"],
            "complexity": "complex",
            "type": "reconciliation_trend",
            "answer_type": "list",
            "id_column": "reconciliation_status",
            "multiturn": True,
            "clarifying_reply": "Just show the breakdown for March 2024, not all 12 months.",
            "reference_sql": "SELECT reconciliation_status, COUNT(*) AS cnt FROM reconciliation_status WHERE reconciliation_date >= '2024-03-01' AND reconciliation_date < '2024-04-01' GROUP BY reconciliation_status"
        },
        {
            "id": "complex_005",
            "question": "For vendors in the Technology industry, show their average payout amount, transaction count, and reconciliation completion rate",
            "expected_contains": ["vendor_list", "industry", "AVG", "COUNT", "reconciliation"],
            "complexity": "complex",
            "type": "industry_analysis",
            "answer_type": "list",
            "id_column": "vendor_id",
            "multiturn": True,
            "clarifying_reply": "Use vendor_payouts for the average payout amount and count; you can skip the reconciliation completion rate for this pass.",
            "reference_sql": "SELECT vp.vendor_id, AVG(vp.amount) AS avg_payout, COUNT(vp.payout_id) AS payout_count FROM vendor_payouts vp JOIN vendor_list vl ON vp.vendor_id = vl.vendor_id WHERE vl.industry = 'Technology' GROUP BY vp.vendor_id"
        }
    ]
}

# ============================================================================
# BENCHMARK RUNNER
# ============================================================================

class BenchmarkRunner:
    """Run benchmarks against different models"""
    
    def __init__(self, output_dir: str = "."):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        load_dotenv()
        # Model lineup: PS Section 7 caps parameter count at <=20B ("not a suggestion").
        # No Qwen model on Bedrock is actually <=20B (smallest is 30B total, MoE ~3B active),
        # so the default is qwen2.5-coder:1.5b running locally via Ollama (genuinely 1.5B).
        # The Bedrock models below are compliant <=20B alternatives for comparison; the 30B
        # Qwen model is kept purely as a non-compliant reference point, not for production use.
        self.models = {
            "qwen2.5-coder-1.5b": "local:ollama",  # DEFAULT, PS-compliant (1.5B, on-device)
            "llama3-1-8b": os.getenv("LLAMA_8B_MODEL_ID", "meta.llama3-1-8b-instruct-v1:0"),
            "mistral-7b": os.getenv("MISTRAL_7B_MODEL_ID", "mistral.mistral-7b-instruct-v0:2"),
            "llama4-scout-17b": os.getenv("LLAMA_SCOUT_17B_MODEL_ID", "meta.llama4-scout-17b-instruct-v1:0"),
            "qwen3-coder-30b-a3b": os.getenv("QWEN_CODER_30B_MODEL_ID", "qwen.qwen3-coder-30b-a3b-v1:0"),  # NOT <=20B
        }
        self.bedrock = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )

        # Execution-based scoring: run generated SQL against the real dataset and
        # compare against a precomputed reference result (ground truth).
        self.db = build_benchmark_db()
        # Lets list comparisons accept a vendor_name column in place of vendor_id
        self.vendor_name_to_id = {
            str(name).strip().lower(): vid
            for vid, name in self.db.execute("SELECT vendor_id, vendor_name FROM vendor_list").fetchall()
        }
        self.reference_cache: Dict[str, List[Tuple]] = {}
        for complexity in ["easy", "moderate", "complex"]:
            for q in TEST_QUESTIONS[complexity]:
                ref_sql = q.get("reference_sql")
                if not ref_sql:
                    continue
                try:
                    self.reference_cache[q["id"]] = self.db.execute(ref_sql).fetchall()
                except Exception as e:
                    logger.warning(f"Reference SQL failed for {q['id']}: {e}")
                    self.reference_cache[q["id"]] = []
        
        self.results = {
            "metadata": {
                "test_date": datetime.now().isoformat(),
                "total_questions": 0,
                "models_tested": list(self.models.keys())
            },
            "by_model": {},
            "comparisons": {}
        }
    
    def run_full_benchmark(self) -> Dict[str, Any]:
        """Run full benchmark suite"""
        logger.info("Starting full benchmark suite")
        
        all_questions = []
        for complexity in ["easy", "moderate", "complex"]:
            all_questions.extend(TEST_QUESTIONS[complexity])
        
        self.results["metadata"]["total_questions"] = len(all_questions)
        
        # Test each model
        for model_name, model_id in self.models.items():
            logger.info(f"Testing model: {model_name}")
            model_results = self._test_model(model_name, model_id, all_questions)
            self.results["by_model"][model_name] = model_results
        
        # Generate comparisons
        self.results["comparisons"] = self._generate_comparisons()
        
        # Save results
        self._save_results()
        
        return self.results
    
    def _test_model(self, model_name: str, model_id: str, 
                   questions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Test a single model against all questions"""
        model_results = {
            "model_id": model_id,
            "started_at": datetime.now().isoformat(),
            "questions_tested": len(questions),
            "results": [],
            "metrics": {}
        }
        
        times = []
        accuracies = []
        groundings = []
        execution_correctness = []
        sql_executed_flags = []
        clarification_flags = []
        
        for question in questions:
            logger.info(f"Testing {model_name} on {question['id']}")
            
            result = self._test_single_question(model_name, question)
            model_results["results"].append(result)
            
            times.append(result["latency_ms"])
            accuracies.append(result["accuracy_score"])
            groundings.append(result["grounding_score"])
            execution_correctness.append(result.get("execution_correctness", 0.0))
            sql_executed_flags.append(1.0 if result.get("sql_executed") else 0.0)
            if question.get("multiturn"):
                clarification_flags.append(1.0 if result.get("asked_clarification") else 0.0)
        
        # Calculate aggregate metrics
        model_results["metrics"] = {
            "avg_latency_ms": statistics.mean(times),
            "median_latency_ms": statistics.median(times),
            "p95_latency_ms": self._percentile(times, 0.95),
            "p99_latency_ms": self._percentile(times, 0.99),
            "avg_accuracy": statistics.mean(accuracies),
            "avg_grounding": statistics.mean(groundings),
            "hallucination_rate": 1 - statistics.mean(groundings),
            "avg_execution_correctness": statistics.mean(execution_correctness),
            "sql_execution_rate": statistics.mean(sql_executed_flags),
            "clarification_rate": statistics.mean(clarification_flags) if clarification_flags else None,
        }
        
        model_results["completed_at"] = datetime.now().isoformat()
        
        return model_results
    
    def _compare_scalar(self, cand_row: Optional[Tuple], ref_row: Optional[Tuple]) -> float:
        """Compare a single-row numeric/text result with 5% relative tolerance per column."""
        if not cand_row or not ref_row:
            return 0.0
        n = min(len(cand_row), len(ref_row))
        if n == 0:
            return 0.0
        matches = 0.0
        for i in range(n):
            c, r = cand_row[i], ref_row[i]
            if r is None:
                matches += 1.0 if c is None else 0.0
                continue
            try:
                c_f, r_f = float(c), float(r)
            except (TypeError, ValueError):
                matches += 1.0 if str(c) == str(r) else 0.0
                continue
            if r_f == 0:
                matches += 1.0 if abs(c_f) < 1e-6 else 0.0
            else:
                matches += 1.0 if abs(c_f - r_f) / abs(r_f) <= 0.05 else 0.0
        return matches / n

    def _compare_list(self, cand_rows: List[Tuple], ref_rows: List[Tuple],
                     id_column: Optional[str], cand_cols: List[str]) -> float:
        """Jaccard similarity between candidate and reference identifier sets.
        Falls back to resolving a vendor_name column to vendor_id so answers that
        return the human-readable name instead of the id aren't unfairly zeroed out."""
        ref_ids = {row[0] for row in ref_rows}
        if id_column and id_column in cand_cols:
            idx = cand_cols.index(id_column)
            cand_ids = {row[idx] for row in cand_rows}
        elif id_column == "vendor_id" and "vendor_name" in cand_cols:
            idx = cand_cols.index("vendor_name")
            cand_ids = {
                self.vendor_name_to_id[str(row[idx]).strip().lower()]
                for row in cand_rows
                if str(row[idx]).strip().lower() in self.vendor_name_to_id
            }
        else:
            cand_ids = {row[0] for row in cand_rows} if cand_cols else set()
        if not ref_ids and not cand_ids:
            return 1.0
        union = cand_ids | ref_ids
        if not union:
            return 0.0
        return len(cand_ids & ref_ids) / len(union)

    def _compare_keyed_rows(self, cand_rows: List[Tuple], ref_rows: List[Tuple],
                           cand_cols: List[str]) -> float:
        """Match multi-row numeric results by a label in the first column (substring match,
        e.g. 'Q3' matches 'Q3 2024'), then compare the remaining columns with 5% tolerance."""
        if not ref_rows:
            return 1.0 if not cand_rows else 0.0
        if not cand_rows:
            return 0.0

        matches = 0.0
        for ref_row in ref_rows:
            ref_key = str(ref_row[0]).strip().lower()
            cand_row = next(
                (row for row in cand_rows if ref_key in str(row[0]).strip().lower()
                 or str(row[0]).strip().lower() in ref_key),
                None,
            )
            if cand_row is None:
                continue
            n = min(len(cand_row), len(ref_row))
            col_matches, col_count = 0.0, 0
            for i in range(1, n):
                c, r = cand_row[i], ref_row[i]
                col_count += 1
                try:
                    c_f, r_f = float(c), float(r)
                except (TypeError, ValueError):
                    col_matches += 1.0 if str(c) == str(r) else 0.0
                    continue
                if r_f == 0:
                    col_matches += 1.0 if abs(c_f) < 1e-6 else 0.0
                else:
                    col_matches += 1.0 if abs(c_f - r_f) / abs(r_f) <= 0.05 else 0.0
            matches += (col_matches / col_count) if col_count else 1.0
        return matches / len(ref_rows)

    def _score_execution(self, sql: str, question: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the extracted SQL for real and score it against the reference result."""
        outcome: Dict[str, Any] = {
            "extracted_sql": sql,
            "sql_executed": False,
            "execution_correctness": 0.0,
            "execution_error": None,
        }

        if not sql:
            outcome["execution_error"] = "no SQL statement found in response"
            return outcome
        if not is_sql_safe(sql):
            outcome["execution_error"] = "blocked: not a read-only SELECT"
            return outcome

        try:
            cursor = self.db.execute(sql)
            cand_rows = cursor.fetchall()
            cand_cols = [d[0] for d in cursor.description] if cursor.description else []
        except Exception as e:
            outcome["execution_error"] = str(e)[:200]
            return outcome

        outcome["sql_executed"] = True
        outcome["row_count"] = len(cand_rows)

        answer_type = question.get("answer_type", "unverifiable")
        if answer_type == "unverifiable":
            # No deterministic ground truth (subjective/open-ended question) - credit successful, non-empty execution
            outcome["execution_correctness"] = 1.0 if cand_rows else 0.5
            return outcome

        ref_rows = self.reference_cache.get(question["id"], [])
        if answer_type == "scalar":
            cand_row = cand_rows[0] if cand_rows else None
            ref_row = ref_rows[0] if ref_rows else None
            outcome["execution_correctness"] = self._compare_scalar(cand_row, ref_row)
        elif answer_type == "list":
            outcome["execution_correctness"] = self._compare_list(
                cand_rows, ref_rows, question.get("id_column"), cand_cols
            )
        elif answer_type == "keyed_rows":
            outcome["execution_correctness"] = self._compare_keyed_rows(cand_rows, ref_rows, cand_cols)

        return outcome

    def _call_model(self, model_name: str, model_id: str, system_prompt: str,
                    messages: List[Dict[str, str]], max_tokens: int = 512,
                    temperature: float = 0.2) -> str:
        """Dispatch to local Ollama or AWS Bedrock depending on the model alias.
        messages: ordered list of {"role": "user"|"assistant", "content": str}"""
        if model_name in LOCAL_MODEL_ALIASES:
            ollama_messages = [{"role": "system", "content": system_prompt}] + [
                {"role": m["role"], "content": m["content"]} for m in messages
            ]
            payload = json.dumps({
                "model": OLLAMA_MODEL_NAME,
                "messages": ollama_messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{OLLAMA_HOST}/api/chat", data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["message"]["content"]

        response = self.bedrock.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        return response["output"]["message"]["content"][0]["text"]

    def _test_single_question(self, model_name: str, 
                             question: Dict[str, Any]) -> Dict[str, Any]:
        """Test model on single question"""
        start_time = time.time()
        model_id = self.models[model_name]

        if question.get("multiturn"):
            return self._test_multiturn_question(model_name, model_id, question, start_time)

        try:
            result_text = self._call_model(
                model_name, model_id, SQL_SYSTEM_PROMPT,
                [{"role": "user", "content": question["question"]}],
                max_tokens=512, temperature=0.2,
            )
            latency = (time.time() - start_time) * 1000

            # Execution-based scoring: actually run the generated SQL against real data
            extracted_sql = extract_sql(result_text)
            execution_result = self._score_execution(extracted_sql, question)

            # Score the response (uses the executed/verified result when ground truth exists)
            accuracy = self._score_accuracy(result_text, question, execution_result)
            grounding = self._score_grounding(result_text, question)
            hallucination = 1.0 - grounding

            return {
                "question_id": question["id"],
                "question": question["question"],
                "complexity": question["complexity"],
                "model": model_name,
                "response": result_text[:500],  # Truncate for storage
                "latency_ms": latency,
                "accuracy_score": accuracy,
                "grounding_score": grounding,
                "hallucination_score": hallucination,
                "timestamp": datetime.now().isoformat(),
                **execution_result,
            }
        
        except Exception as e:
            logger.error(f"Error testing question {question['id']}: {e}")
            return {
                "question_id": question["id"],
                "question": question["question"],
                "complexity": question["complexity"],
                "model": model_name,
                "error": str(e),
                "latency_ms": (time.time() - start_time) * 1000,
                "accuracy_score": 0.0,
                "grounding_score": 0.0,
                "hallucination_score": 1.0,
                "extracted_sql": "",
                "sql_executed": False,
                "execution_correctness": 0.0,
                "execution_error": str(e),
            }

    def _test_multiturn_question(self, model_name: str, model_id: str,
                                question: Dict[str, Any], start_time: float) -> Dict[str, Any]:
        """Test an ambiguous question over two turns: model should ask a clarifying
        question first, then produce SQL once the ambiguity is resolved."""
        try:
            clarifying_text = self._call_model(
                model_name, model_id, CLARIFYING_SYSTEM_PROMPT,
                [{"role": "user", "content": question["question"]}],
                max_tokens=512, temperature=0.2,
            )
            asked_clarification = "?" in clarifying_text and not extract_sql(clarifying_text)

            result_text = self._call_model(
                model_name, model_id, SQL_SYSTEM_PROMPT,
                [
                    {"role": "user", "content": question["question"]},
                    {"role": "assistant", "content": clarifying_text},
                    {"role": "user", "content": question["clarifying_reply"]},
                ],
                max_tokens=512, temperature=0.2,
            )
            latency = (time.time() - start_time) * 1000

            extracted_sql = extract_sql(result_text)
            execution_result = self._score_execution(extracted_sql, question)
            accuracy = self._score_accuracy(result_text, question, execution_result)
            grounding = self._score_grounding(result_text, question)
            hallucination = 1.0 - grounding

            return {
                "question_id": question["id"],
                "question": question["question"],
                "complexity": question["complexity"],
                "model": model_name,
                "clarifying_question": clarifying_text[:300],
                "asked_clarification": asked_clarification,
                "response": result_text[:500],
                "latency_ms": latency,
                "accuracy_score": accuracy,
                "grounding_score": grounding,
                "hallucination_score": hallucination,
                "timestamp": datetime.now().isoformat(),
                **execution_result,
            }

        except Exception as e:
            logger.error(f"Error testing multiturn question {question['id']}: {e}")
            return {
                "question_id": question["id"],
                "question": question["question"],
                "complexity": question["complexity"],
                "model": model_name,
                "error": str(e),
                "asked_clarification": False,
                "latency_ms": (time.time() - start_time) * 1000,
                "accuracy_score": 0.0,
                "grounding_score": 0.0,
                "hallucination_score": 1.0,
                "extracted_sql": "",
                "sql_executed": False,
                "execution_correctness": 0.0,
                "execution_error": str(e),
            }
    
    def _score_accuracy(self, response: str, question: Dict[str, Any],
                       execution_result: Optional[Dict[str, Any]] = None) -> float:
        """Score response accuracy (0-1): use the math-verified execution result when a
        reference answer exists, otherwise fall back to keyword matching."""
        if execution_result is not None and question.get("answer_type") in ("scalar", "list", "keyed_rows"):
            return execution_result.get("execution_correctness", 0.0)

        score = 0.0
        # Check if response contains expected keywords
        for keyword in question.get("expected_contains", []):
            if keyword.lower() in response.lower():
                score += 1
        
        max_keywords = max(len(question.get("expected_contains", [])), 1)
        return min(score / max_keywords, 1.0)
    
    def _score_grounding(self, response: str, question: Dict[str, Any]) -> float:
        """Score grounding (is it referencing actual data)?"""
        # Simple heuristic: check for SQL query
        if "SELECT" in response.upper():
            # Has SQL, likely grounded
            return 0.8
        elif any(keyword in response.upper() for keyword in ["VENDOR", "TRANSACTION", "PAYOUT"]):
            return 0.6
        else:
            # No grounding indicators
            return 0.2
    
    def _percentile(self, data: List[float], percentile: float) -> float:
        """Calculate percentile"""
        sorted_data = sorted(data)
        idx = int(len(sorted_data) * percentile)
        return sorted_data[min(idx, len(sorted_data) - 1)]
    
    def _generate_comparisons(self) -> Dict[str, Any]:
        """Generate model comparison data"""
        comparisons = {
            "by_complexity": {},
            "by_type": {},
            "overall_rankings": {}
        }
        
        # Compare by complexity
        for complexity in ["easy", "moderate", "complex"]:
            complexity_results = {}
            
            for model_name, model_data in self.results["by_model"].items():
                matching_results = [r for r in model_data["results"] 
                                  if r.get("complexity") == complexity]
                
                if matching_results:
                    complexity_results[model_name] = {
                        "avg_accuracy": statistics.mean([r["accuracy_score"] for r in matching_results]),
                        "avg_latency_ms": statistics.mean([r["latency_ms"] for r in matching_results]),
                        "count": len(matching_results)
                    }
            
            comparisons["by_complexity"][complexity] = complexity_results
        
        # Overall rankings
        rankings = {}
        for metric in ["avg_accuracy", "avg_execution_correctness", "avg_latency_ms", "avg_grounding"]:
            ranked = sorted(
                [(m, d["metrics"].get(metric, 0)) for m, d in self.results["by_model"].items()],
                key=lambda x: x[1],
                reverse=metric != "avg_latency_ms"
            )
            rankings[metric] = [{"model": m, "value": v} for m, v in ranked]
        
        comparisons["overall_rankings"] = rankings
        
        return comparisons
    
    def _save_results(self):
        """Save benchmark results to file"""
        filename = os.path.join(
            self.output_dir,
            f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        
        with open(filename, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        logger.info(f"Results saved to {filename}")
        return filename
    
    def generate_report(self) -> str:
        """Generate human-readable report"""
        report = []
        report.append("=" * 80)
        report.append("TBX FINANCE ASSISTANT - BENCHMARK REPORT")
        report.append("=" * 80)
        
        report.append(f"\nTest Date: {self.results['metadata']['test_date']}")
        report.append(f"Total Questions: {self.results['metadata']['total_questions']}")
        report.append(f"Models Tested: {', '.join(self.results['metadata']['models_tested'])}")
        
        # Model metrics
        report.append("\n" + "=" * 80)
        report.append("MODEL PERFORMANCE METRICS")
        report.append("=" * 80)
        
        for model_name, model_data in self.results["by_model"].items():
            report.append(f"\n{model_name.upper()}:")
            metrics = model_data["metrics"]
            report.append(f"  Avg Accuracy (math-verified where ground truth exists): {metrics['avg_accuracy']:.2%}")
            report.append(f"  Avg Execution Correctness (real, executed+verified): {metrics['avg_execution_correctness']:.2%}")
            report.append(f"  SQL Execution Rate (ran without error): {metrics['sql_execution_rate']:.2%}")
            if metrics.get("clarification_rate") is not None:
                report.append(f"  Clarification Rate (multiturn, asked before answering): {metrics['clarification_rate']:.2%}")
            report.append(f"  Avg Grounding: {metrics['avg_grounding']:.2%}")
            report.append(f"  Hallucination Rate: {metrics['hallucination_rate']:.2%}")
            report.append(f"  Avg Latency: {metrics['avg_latency_ms']:.0f}ms")
            report.append(f"  P95 Latency: {metrics['p95_latency_ms']:.0f}ms")
        
        # Comparisons
        report.append("\n" + "=" * 80)
        report.append("PERFORMANCE BY COMPLEXITY")
        report.append("=" * 80)
        
        for complexity, models in self.results["comparisons"]["by_complexity"].items():
            report.append(f"\n{complexity.upper()}:")
            for model, metrics in models.items():
                report.append(f"  {model}: Accuracy={metrics['avg_accuracy']:.2%}, Latency={metrics['avg_latency_ms']:.0f}ms")
        
        # Rankings
        report.append("\n" + "=" * 80)
        report.append("OVERALL RANKINGS")
        report.append("=" * 80)
        
        for metric, rankings in self.results["comparisons"]["overall_rankings"].items():
            report.append(f"\n{metric.replace('_', ' ').title()}:")
            for rank, item in enumerate(rankings, 1):
                report.append(f"  {rank}. {item['model']}: {item['value']:.2f}")
        
        report.append("\n" + "=" * 80)
        
        return "\n".join(report)

# ============================================================================
# MAIN BENCHMARK EXECUTION
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    runner = BenchmarkRunner()
    results = runner.run_full_benchmark()
    
    # Print report
    report = runner.generate_report()
    print(report)
    
    # Save report
    report_file = os.path.join(runner.output_dir, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with open(report_file, 'w') as f:
        f.write(report)
    
    print(f"\nFull results saved to {runner.output_dir}")
