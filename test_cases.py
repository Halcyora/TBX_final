"""
Comprehensive test cases for TBX Finance Assistant
"""
import httpx
import json
import time

BASE_URL = "http://localhost:8000"

test_cases = [
    {
        "name": "Count transactions",
        "query": "How many transactions are in the system?",
        "expected_rows": 1,
        "should_have_results": True
    },
    {
        "name": "List banks",
        "query": "List all banks",
        "expected_rows": None,  # Variable
        "should_have_results": True
    },
    {
        "name": "Transaction by vendor",
        "query": "Show transactions from vendor_id 1",
        "expected_rows": None,
        "should_have_results": True
    },
    {
        "name": "Account balances",
        "query": "What are the account balances?",
        "expected_rows": None,
        "should_have_results": True
    },
    {
        "name": "Invalid query clarification",
        "query": "xyz abc 123",
        "expected_rows": None,
        "should_have_results": False
    }
]

def run_tests():
    print("=" * 70)
    print("TBX FINANCE ASSISTANT - TEST SUITE")
    print("=" * 70)
    
    results = []
    
    try:
        # Create session
        sess_resp = httpx.post(f"{BASE_URL}/sessions/create", timeout=5.0)
        session_id = sess_resp.json()['session_id']
        print(f"\n✓ Session created: {session_id[:8]}...\n")
    except Exception as e:
        print(f"✗ Failed to create session: {e}")
        return
    
    for i, test in enumerate(test_cases, 1):
        print(f"Test {i}: {test['name']}")
        print(f"  Query: {test['query']}")
        
        try:
            chat_payload = {
                'session_id': session_id,
                'message': {
                    'content': test['query'],
                    'role': 'user'
                }
            }
            
            start = time.time()
            chat_resp = httpx.post(f"{BASE_URL}/chat", json=chat_payload, timeout=60.0)
            elapsed = time.time() - start
            
            if chat_resp.status_code == 200:
                result = chat_resp.json()
                
                rows = len(result.get('query_results', []))
                stages = len(result.get('processing_stages_completed', []))
                answer = result.get('message', '')[:60]
                
                # Check result
                has_results = rows > 0
                expected = test['should_have_results']
                
                if has_results == expected:
                    status = "✓ PASS"
                    results.append(True)
                else:
                    status = "✗ FAIL"
                    results.append(False)
                
                print(f"  {status}")
                print(f"    - Response time: {elapsed:.2f}s")
                print(f"    - Rows returned: {rows}")
                print(f"    - Stages completed: {stages}")
                print(f"    - Answer: {answer}...")
                
                if stages > 0:
                    stages_list = result.get('processing_stages_completed', [])
                    print(f"    - Pipeline: {' → '.join(stages_list)}")
                
            else:
                print(f"  ✗ FAIL - HTTP {chat_resp.status_code}")
                results.append(False)
                
        except Exception as e:
            print(f"  ✗ FAIL - {type(e).__name__}: {str(e)[:50]}")
            results.append(False)
        
        print()
    
    # Summary
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    print("=" * 70)
    
    if passed == total:
        print("✓ All tests passed!")
    else:
        print(f"✗ {total - passed} test(s) failed")

if __name__ == "__main__":
    run_tests()
