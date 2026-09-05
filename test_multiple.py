import httpx
import json

test_queries = [
    "Show me total transactions",
    "List all banks in the system",
    "How many credit vs debit transactions",
    "Show me accounts with negative balances"
]

try:
    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)
        
        # Create session
        sess_resp = httpx.post('http://localhost:8000/sessions/create', timeout=5.0)
        session_id = sess_resp.json()['session_id']
        
        # Send chat
        chat_payload = {
            'session_id': session_id,
            'message': {
                'content': query,
                'role': 'user'
            }
        }
        chat_resp = httpx.post('http://localhost:8000/chat', json=chat_payload, timeout=30.0)
        
        if chat_resp.status_code == 200:
            result = chat_resp.json()
            answer = result.get('message', '')[:100]
            rows = len(result.get('query_results', []))
            print(f"✓ SUCCESS")
            print(f"  Result: {rows} rows")
            print(f"  Answer: {answer}...")
        else:
            print(f"✗ FAILED: {chat_resp.text[:100]}")

except Exception as e:
    print(f"✗ Test error: {str(e)}")
