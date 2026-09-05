import httpx
import json

# Test 1: Query for account numbers (should be decrypted)
test_queries = [
    "Show me all account numbers and their balances",
    "Which account has the highest balance and what's its account number?",
    "Show transactions with UTR numbers"
]

print("Testing Runtime Decryption System")
print("="*60)

for query in test_queries:
    print(f"\nQuery: {query}")
    print("-"*60)
    
    try:
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
            rows = result.get('query_results', [])
            
            if rows:
                # Check if sensitive fields are present and decrypted (not encrypted)
                first_row = rows[0]
                account_number = first_row.get('account_number', 'N/A')
                utr_number = first_row.get('utr_number', 'N/A')
                
                print(f"✓ Success: {len(rows)} rows returned")
                print(f"  Sample account_number: {account_number[:50]}")
                print(f"  Sample utr_number: {utr_number[:50] if utr_number != 'N/A' else 'N/A'}")
                
                # Check if they look decrypted (no encryption prefix)
                if account_number and not account_number.startswith('gAAAAAB'):
                    print("  ✓ Account numbers appear DECRYPTED")
                elif account_number == 'N/A':
                    print("  - No account_number column in results")
            else:
                print(f"✓ Query executed but returned 0 rows")
        else:
            print(f"✗ Error: {chat_resp.text[:200]}")
    except Exception as e:
        print(f"✗ Test failed: {str(e)}")

print("\n" + "="*60)
print("Decryption test complete!")
