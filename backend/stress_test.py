"""
Quick stress test: sends a diverse batch of prompts to the running backend
and reports per-query pass/fail, timing, and pipeline stage reached.
"""
import time
import json
import urllib.request

BASE_URL = "http://localhost:8000"

QUERIES = [
    "List all banks in the system",
    "Show me accounts with negative balances",
    "List all accounts at ICICI BANK LIMITED",
    "List all accounts at HDFC BANK LIMITED",
    "What is the total amount of transactions from HDFC Bank?",
    "How many credit vs debit transactions are there?",
    "Which accounts have zero available balance?",
    "Show transactions with missing UTR or reference ID",
    "What is the average transaction amount by account?",
    "What is the most common transaction date?",
    "What's the available balance for account 50200013729069?",
    "Which accounts have a negative available balance?",
    "Show me all accounts with balance > 10000",
    "What is the highest transaction amount?",
    "Give me account number of transactions in icici bank",
    "asdkjaslkdj random gibberish query xyz",
    "Show all transactions in the last 2 years",
    "Compare HDFC and ICICI total transaction volumes",
]


def post_json(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    session = post_json("/sessions/create", {})
    session_id = session["session_id"]
    print(f"Session: {session_id}\n")

    results = []
    for i, q in enumerate(QUERIES, 1):
        start = time.time()
        try:
            resp = post_json(
                "/chat",
                {"session_id": session_id, "message": {"content": q, "role": "user"}},
            )
            elapsed = time.time() - start
            stages = resp.get("processing_stages", [])
            rows = len(resp.get("query_results", []))
            confidence = resp.get("confidence_score", 0)
            error_msg = "wasn't able to retrieve" in resp.get("message", "")
            status = "FAIL" if error_msg else "OK"
            results.append((status, q, elapsed, stages, rows, confidence))
            print(f"[{i:2d}] {status:4s} ({elapsed:5.2f}s) rows={rows:3d} conf={confidence:.2f} stages={','.join(stages)}")
            print(f"      Q: {q}")
            if status == "FAIL":
                print(f"      MSG: {resp.get('message')}")
        except Exception as e:
            elapsed = time.time() - start
            results.append(("ERROR", q, elapsed, [], 0, 0))
            print(f"[{i:2d}] ERROR ({elapsed:5.2f}s) {e}")
            print(f"      Q: {q}")

    print("\n=== SUMMARY ===")
    ok = sum(1 for r in results if r[0] == "OK")
    fail = sum(1 for r in results if r[0] == "FAIL")
    err = sum(1 for r in results if r[0] == "ERROR")
    avg_time = sum(r[2] for r in results) / len(results)
    print(f"Total: {len(results)} | OK: {ok} | FAIL: {fail} | ERROR: {err} | Avg time: {avg_time:.2f}s")


if __name__ == "__main__":
    main()
