"""
Manual, ad-hoc test: run complex, multi-table questions that require decrypting sensitive
columns (account_number, utr_number) at runtime, through the REAL compiled pipeline
(backend/langgraph_flow.build_finance_graph), against the live model endpoint. Reports the
generated SQL, whether the returned sensitive values were actually decrypted, and end-to-end
latency - not part of the automated benchmark suite (benchmarks/run_benchmark.py), this is a
one-off performance/correctness check for the encryption work.

Usage: python scripts/test_decryption_queries.py [small|large]
Requires ENCRYPTION_KEY and LLM_BASE_URL/LLM_MODEL_NAME set (see .env).
"""

import asyncio
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

import database
from database import FinanceDB
from langgraph_flow import build_finance_graph, FinanceAssistantState

QUESTIONS = [
    "Show me the account number and bank name for accounts with a negative balance",
    "List the UTR, transaction amount, account number, and bank name for the top 10 largest transactions",
    "Show transactions with a UTR that is not null, along with the account number and bank name, for the top 5 largest amounts",
    "For each bank, show the total transaction volume and the account number of the account with the highest available balance",
    "Give me the account number for the account with the most transactions, along with its bank name",
]

# A real decrypted account number/UTR looks like our plaintext formats; ciphertext is base64
# and typically longer / has no recognizable structure. Cheap heuristic for a sanity check only.
LOOKS_LIKE_PLAUSIBLE_PLAINTEXT = re.compile(r"^(\d{10,20}|UTR[0-9A-F]{10,20})$")


async def run_question(graph, question: str):
    state = FinanceAssistantState(user_query=question)
    t0 = time.time()
    result = await graph.ainvoke(state.model_dump())
    elapsed = time.time() - t0

    rows = result.get("query_results") or []
    sql = result.get("sql_query") or ""
    stage_details = result.get("stage_details", {})

    sensitive_values = []
    for row in rows[:5]:
        for key, val in row.items():
            if val and any(col in key.lower() for col in ("account_number", "utr_number")):
                sensitive_values.append((key, val))

    print(f"Q: {question}")
    print(f"  latency: {elapsed:.2f}s | rows: {len(rows)} | stages: {result.get('processing_stages_completed')}")
    print(f"  self-consistency: {stage_details.get('sql_generation')}")
    print(f"  sql: {sql[:200].strip()}...")
    if sensitive_values:
        for col, val in sensitive_values[:4]:
            looks_ok = bool(LOOKS_LIKE_PLAUSIBLE_PLAINTEXT.match(str(val)))
            print(f"  decrypted {col}: {val!r}  {'(looks plausible)' if looks_ok else '(!! check this)'}")
    else:
        print("  (no sensitive columns in the result - model may not have SELECTed them)")
    if result.get("execution_error"):
        print(f"  execution_error: {result['execution_error']}")
    print()
    return elapsed


async def main(dataset: str):
    print(f"=== Dataset: {dataset} ===\n")
    database._db_instance = FinanceDB(db_path=":memory:", dataset=dataset)
    graph = build_finance_graph()

    latencies = []
    for q in QUESTIONS:
        latencies.append(await run_question(graph, q))

    print(f"Average latency: {sum(latencies)/len(latencies):.2f}s | Max: {max(latencies):.2f}s")


if __name__ == "__main__":
    dataset_arg = sys.argv[1] if len(sys.argv) > 1 else "small"
    asyncio.run(main(dataset_arg))
