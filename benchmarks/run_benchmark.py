"""
Benchmarking Suite for TBX Finance Assistant
Test different models against diverse TBX financial data questions
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

# AWS Bedrock Nova Micro: 1.3B parameters, PS Section 7 compliant (<=20B params)
NOVA_MICRO_MODEL_ID = "amazon.nova-micro-v1:0"

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
    """In-memory DuckDB with TBX schema (bank, account, transaction) for execution scoring."""
    con = duckdb.connect(database=":memory:")
    for table in ["bank", "account", "transaction"]:
        csv_path = DATA_DIR / f"{table}.csv"
        if csv_path.exists():
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_csv_auto('{csv_path.as_posix()}', ALL_VARCHAR=TRUE)")
        else:
            print(f"Warning: {csv_path} not found, skipping table {table}")
    return con

# System prompt reused from backend/prompts.py so the benchmark reflects real grounding behavior
SQL_SYSTEM_PROMPT = """You are an expert SQL developer for TBX financial data analysis.
Convert natural language questions into precise DuckDB SQL queries.

DATABASE SCHEMA (TBX Finance Assistant):

bank:
- bank_code (VARCHAR, PRIMARY KEY): Bank code (HDFC, ICIC, SBIN, UTIB, KKBK, CNRB, UBIN, AUBL, etc.)
- bank_name (VARCHAR): Full bank name (e.g., HDFC BANK LIMITED)

account:
- account_id (VARCHAR, PRIMARY KEY): Unique account ID (UUID)
- entity_id (VARCHAR): Entity/customer ID (UUID)
- account_number (VARCHAR): Account number (SENSITIVE - mask in output)
- program_id (VARCHAR): Program ID (0, 4, 21, 46, 99)
- available_balance (VARCHAR): Balance (can be negative, zero, or extreme values)
- bank_code (VARCHAR, FOREIGN KEY): Reference to bank.bank_code

transaction:
- transaction_id (VARCHAR, PRIMARY KEY): Unique transaction ID (UUID)
- account_id (VARCHAR, FOREIGN KEY): Reference to account.account_id
- transaction_date (VARCHAR): Timestamp (YYYY-MM-DD HH:MM:SS.microseconds)
- transaction_type (VARCHAR): 'credit' or 'debit' (ONLY these two values)
- description (VARCHAR): Transaction description
- transaction_amount (VARCHAR): Amount (can be 0.00, extreme values, etc.)
- transaction_reference_id (VARCHAR): Reference number (often empty, can be duplicated)
- utr_number (VARCHAR): UTR (often empty, encrypted, or plaintext)

RULES:
1. Use date filters ONLY when the question explicitly mentions a time period.
2. Join tables only when necessary (e.g., JOIN bank ON account.bank_code = bank.bank_code).
3. Use SUM/COUNT/AVG/MIN/MAX for aggregations.
4. Cast numeric columns: CAST(available_balance AS DECIMAL), CAST(transaction_amount AS DECIMAL).
5. Filter transaction_type using ONLY 'credit' or 'debit' (case-sensitive).
6. Handle NULL/empty fields: use '' for empty strings.
7. Assume 'today' is 2026-09-05 for relative date phrases like 'last month'.
8. Always include ID columns (account_id, transaction_id) in SELECT for unique identification.

OUTPUT FORMAT: Return ONLY the SQL query, no markdown fences, no explanation."""

# System prompt for turn 1 of multiturn questions: ambiguous requests should be
# clarified before any SQL is written, instead of guessing at undefined thresholds/periods.
CLARIFYING_SYSTEM_PROMPT = SQL_SYSTEM_PROMPT + """

CLARIFICATION RULE: If the question relies on an undefined threshold, time period, or
metric definition that would change the SQL depending on interpretation (e.g., 'high variance',
'large transactions', 'recent activity'), do NOT write SQL yet. Instead, ask ONE short
clarifying question to resolve the ambiguity. If the question is already unambiguous,
answer normally per the OUTPUT FORMAT above."""

# ============================================================================
# TEST QUESTION SETS (TBX Schema)
# ============================================================================

TEST_QUESTIONS = {
    "easy": [
        {
            "id": "easy_001",
            "question": "How much did we spend in June 2026?",
            "expected_contains": ["SUM", "2026-06"],
            "complexity": "easy",
            "type": "total_spend",
            "answer_type": "scalar",
            "reference_sql": "SELECT SUM(CAST(transaction_amount AS DECIMAL)) AS total FROM transaction WHERE transaction_date >= '2026-06-01' AND transaction_date < '2026-07-01'"
        },
        {
            "id": "easy_002",
            "question": "How many credit transactions are there?",
            "expected_contains": ["COUNT", "credit"],
            "complexity": "easy",
            "type": "count_by_type",
            "answer_type": "scalar",
            "reference_sql": "SELECT COUNT(*) AS cnt FROM transaction WHERE transaction_type = 'credit'"
        },
        {
            "id": "easy_003",
            "question": "Show me accounts with negative balances",
            "expected_contains": ["available_balance", "<", "0"],
            "complexity": "easy",
            "type": "negative_balance_accounts",
            "answer_type": "list",
            "id_column": "account_id",
            "reference_sql": "SELECT account_id, available_balance FROM account WHERE CAST(available_balance AS DECIMAL) < 0"
        },
        {
            "id": "easy_004",
            "question": "Which banks are in the database?",
            "expected_contains": ["bank_name", "bank_code"],
            "complexity": "easy",
            "type": "bank_list",
            "answer_type": "list",
            "id_column": "bank_code",
            "reference_sql": "SELECT bank_code, bank_name FROM bank"
        },
        {
            "id": "easy_005",
            "question": "How many transactions do we have?",
            "expected_contains": ["COUNT", "transaction"],
            "complexity": "easy",
            "type": "count_all",
            "answer_type": "scalar",
            "reference_sql": "SELECT COUNT(*) AS cnt FROM transaction"
        }
    ],
    
    "moderate": [
        {
            "id": "mod_001",
            "question": "Show total spending by bank",
            "expected_contains": ["GROUP BY", "bank", "SUM"],
            "complexity": "moderate",
            "type": "bank_breakdown",
            "answer_type": "list",
            "id_column": "bank_code",
            "reference_sql": "SELECT b.bank_code, b.bank_name, SUM(CAST(t.transaction_amount AS DECIMAL)) AS total FROM account a JOIN bank b ON a.bank_code = b.bank_code JOIN transaction t ON a.account_id = t.account_id GROUP BY b.bank_code, b.bank_name"
        },
        {
            "id": "mod_002",
            "question": "Show average transaction amount by transaction type",
            "expected_contains": ["GROUP BY", "transaction_type", "AVG"],
            "complexity": "moderate",
            "type": "avg_by_type",
            "answer_type": "list",
            "id_column": "transaction_type",
            "reference_sql": "SELECT transaction_type, AVG(CAST(transaction_amount AS DECIMAL)) AS avg_amount, COUNT(*) as count FROM transaction GROUP BY transaction_type"
        },
        {
            "id": "mod_003",
            "question": "What is the top 5 largest transactions?",
            "expected_contains": ["ORDER BY", "DESC", "LIMIT 5"],
            "complexity": "moderate",
            "type": "top_transactions",
            "answer_type": "list",
            "id_column": "transaction_id",
            "reference_sql": "SELECT transaction_id, transaction_amount, transaction_date FROM transaction ORDER BY CAST(transaction_amount AS DECIMAL) DESC LIMIT 5"
        },
        {
            "id": "mod_004",
            "question": "Show accounts by program ID with balance totals",
            "expected_contains": ["GROUP BY", "program_id"],
            "complexity": "moderate",
            "type": "program_breakdown",
            "answer_type": "list",
            "id_column": "program_id",
            "reference_sql": "SELECT program_id, COUNT(*) AS account_count, SUM(CAST(available_balance AS DECIMAL)) AS total_balance FROM account GROUP BY program_id"
        },
        {
            "id": "mod_005",
            "question": "How many transactions have missing UTR?",
            "expected_contains": ["COUNT", "utr_number", "=", "''"],
            "complexity": "moderate",
            "type": "missing_fields",
            "answer_type": "scalar",
            "reference_sql": "SELECT COUNT(*) AS missing_utr_count FROM transaction WHERE utr_number = ''"
        }
    ],
    
    "complex": [
        {
            "id": "complex_001",
            "question": "For each bank, show average account balance and transaction count",
            "expected_contains": ["GROUP BY", "bank", "AVG", "COUNT"],
            "complexity": "complex",
            "type": "bank_analysis",
            "answer_type": "list",
            "id_column": "bank_code",
            "reference_sql": "SELECT b.bank_code, b.bank_name, COUNT(DISTINCT a.account_id) AS account_count, AVG(CAST(a.available_balance AS DECIMAL)) AS avg_balance, SUM(CAST(t.transaction_amount AS DECIMAL)) AS total_transactions FROM account a JOIN bank b ON a.bank_code = b.bank_code LEFT JOIN transaction t ON a.account_id = t.account_id GROUP BY b.bank_code, b.bank_name"
        },
        {
            "id": "complex_002",
            "question": "Show accounts with extreme balances (over 100M or under -100M) and their transaction activity",
            "expected_contains": ["ABS", "available_balance", ">", "100000000"],
            "complexity": "complex",
            "type": "extreme_balances",
            "answer_type": "list",
            "id_column": "account_id",
            "reference_sql": "SELECT a.account_id, CAST(a.available_balance AS DECIMAL) AS balance, COUNT(t.transaction_id) AS txn_count FROM account a LEFT JOIN transaction t ON a.account_id = t.account_id WHERE ABS(CAST(a.available_balance AS DECIMAL)) > 100000000 GROUP BY a.account_id, a.available_balance"
        },
        {
            "id": "complex_003",
            "question": "Find transactions with zero or micro amounts and show their distribution",
            "expected_contains": ["amount", "0.00", "0.01"],
            "complexity": "complex",
            "type": "micro_transactions",
            "answer_type": "list",
            "id_column": "transaction_type",
            "reference_sql": "SELECT transaction_type, CAST(transaction_amount AS DECIMAL) as amount, COUNT(*) as count FROM transaction WHERE CAST(transaction_amount AS DECIMAL) <= 0.01 GROUP BY transaction_type, CAST(transaction_amount AS DECIMAL)"
        },
        {
            "id": "complex_004",
            "question": "Show the longest gaps between transactions for each account",
            "expected_contains": ["MAX", "transaction_date", "account_id"],
            "complexity": "complex",
            "type": "transaction_gaps",
            "answer_type": "list",
            "id_column": "account_id",
            "reference_sql": "SELECT account_id, MAX(transaction_date) AS last_transaction, MIN(transaction_date) AS first_transaction FROM transaction GROUP BY account_id"
        },
        {
            "id": "complex_005",
            "question": "Find duplicate reference IDs or UTRs that appear in multiple accounts",
            "expected_contains": ["COUNT", "HAVING", "transaction_reference_id"],
            "complexity": "complex",
            "type": "duplicate_references",
            "answer_type": "list",
            "id_column": "reference_id",
            "reference_sql": "SELECT transaction_reference_id, COUNT(DISTINCT account_id) AS account_count, COUNT(*) AS total_count FROM transaction WHERE transaction_reference_id != '' GROUP BY transaction_reference_id HAVING COUNT(DISTINCT account_id) > 1"
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
        # Amazon Nova Micro: 1.3B parameters, AWS-native Bedrock model, PS-compliant
        # Alternative models for benchmarking (all <=20B params)
        self.models = {
            "amazon.nova-micro": os.getenv("NOVA_MICRO_MODEL_ID", "amazon.nova-micro-v1:0"),  # DEFAULT, PS-compliant (1.3B)
            "llama3-1-8b": os.getenv("LLAMA_8B_MODEL_ID", "meta.llama3-1-8b-instruct-v1:0"),
            "mistral-7b": os.getenv("MISTRAL_7B_MODEL_ID", "mistral.mistral-7b-instruct-v0:2"),
            "llama4-scout-17b": os.getenv("LLAMA_SCOUT_17B_MODEL_ID", "meta.llama4-scout-17b-instruct-v1:0"),
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
        # Build bank_code to bank_name mapping for TBX schema
        self.bank_code_to_name = {
            code: name
            for code, name in self.db.execute("SELECT bank_code, bank_name FROM bank").fetchall()
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
        """Call AWS Bedrock model and return response.
        messages: ordered list of {"role": "user"|"assistant", "content": str}"""
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
