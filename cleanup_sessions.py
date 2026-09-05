import json
from pathlib import Path

store_path = Path("./data/sessions_store.json")
if store_path.exists():
    with open(store_path) as f:
        sessions = json.load(f)
    
    original_count = len(sessions)
    # Keep only sessions with messages
    cleaned = {sid: s for sid, s in sessions.items() if s.get("messages", [])}
    
    with open(store_path, "w") as f:
        json.dump(cleaned, f, default=str, indent=2)
    
    print(f"✓ Cleaned sessions store:")
    print(f"  - Removed {original_count - len(cleaned)} empty sessions")
    print(f"  - Kept {len(cleaned)} sessions with messages")
