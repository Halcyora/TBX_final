import httpx
import json

try:
    # Create a session
    sess_resp = httpx.post('http://localhost:8000/sessions/create', timeout=5.0)
    session_id = sess_resp.json()['session_id']
    print(f'✓ Session created: {session_id[:8]}...')
    
    # Send a chat message
    chat_payload = {
        'session_id': session_id,
        'message': {
            'content': 'Show me total transactions',
            'role': 'user'
        }
    }
    chat_resp = httpx.post('http://localhost:8000/chat', json=chat_payload, timeout=30.0)
    
    if chat_resp.status_code == 200:
        result = chat_resp.json()
        print(f'✓ Chat works - Response status: {chat_resp.status_code}')
        answer = result.get('message', '')[:80]
        print('  - Answer:', answer)
        rows = len(result.get('query_results', []))
        print('  - Results:', rows, 'rows')
        stages = len(result.get('processing_stages_completed', []))
        print('  - Stages:', stages, 'completed')
    else:
        print('✗ Chat error:', chat_resp.text[:200])
except Exception as e:
    print('✗ Chat test failed:', str(e))
