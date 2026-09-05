# Account Number Encryption

> 📚 **Full Docs**: See [../DOCS.md](../DOCS.md) for complete guide index  
> **Quick Judge Guide**: See [JUDGE_DECRYPTION_GUIDE.md](JUDGE_DECRYPTION_GUIDE.md)

## Encryption Flow

```mermaid
sequenceDiagram
    participant DB as Database<br/>Load
    participant Crypto as Encryption<br/>Module
    participant Query as Query<br/>Execution
    participant API as API<br/>Response
    
    DB->>Crypto: Read account numbers
    Crypto->>Crypto: Encrypt with Fernet key
    Crypto->>Query: Store encrypted
    Query->>Query: Execute SQL (encrypted)
    Query->>API: Return results
    API->>API: Mask: ****3729069
    API->>API: Add: account_number_encrypted
    note over API: ✅ Send to frontend
```

## Configuration (3 Steps)

### Encryption Setup Steps

```mermaid
flowchart LR
    A["Step 1<br/>Generate Key"]
    B["Step 2<br/>Set .env"]
    C["Step 3<br/>Install<br/>cryptography"]
    D["✅ Ready"]
    
    A --> B
    B --> C
    C --> D
    
    style A fill:#f3e5f5
    style B fill:#e1f5ff
    style C fill:#fff9c4
    style D fill:#c8e6c9
```

**1. Generate Key**
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**2. Set .env**
```env
ENCRYPTION_KEY=J4vHHUHhlp3kxcVb_qFECV-SP3CIwmMObS1ti9deygo=
DECRYPTION_CODES=judge_code,admin,verify
```

**3. Install**
```bash
pip install cryptography>=41.0.0
```

## Security

✅ Encrypted at rest (Fernet symmetric)  
✅ Masked in display (****3729069)  
✅ Code-based access control  
✅ Audit logged  
✅ No performance penalty  

### Security Layers

```mermaid
graph TD
    A["Account Number<br/>50200013729069"]
    B["Layer 1: Encryption<br/>Fernet Symmetric"]
    C["Encrypted Value<br/>gAAAAABl9sX5..."]
    D["Layer 2: Storage"]
    E["Database<br/>Encrypted"]
    F["Layer 3: Display"]
    G["Mask in UI<br/>****3729069"]
    H["Layer 4: Decryption<br/>Valid Code Only"]
    I{Decryption<br/>Code<br/>Valid?}
    J["✅ Reveal<br/>50200013729069"]
    K["❌ Deny<br/>Invalid Code"]
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
    I -->|Yes| J
    I -->|No| K
    
    style A fill:#f3e5f5
    style B fill:#ffcdd2
    style E fill:#ffe0b2
    style G fill:#fff9c4
    style J fill:#c8e6c9
    style K fill:#ffcdd2
```

## API Endpoints

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as API

    FE->>API: POST /chat<br/>{session_id, message}
    API-->>FE: query_results, confidence,<br/>grounding_info (account_number_encrypted,<br/>account_number_display)

    FE->>API: POST /decrypt<br/>{encrypted_account_number, decryption_code}
    API-->>FE: success: true, account_number
    API-->>FE: success: false, error
```

## Files Modified

| File | Change | Status |
|------|--------|--------|
| `backend/encryption.py` | Encryption utilities | ✅ New |
| `backend/database.py` | Auto-encrypt on load | ✅ Modified |
| `backend/main.py` | /decrypt endpoint | ✅ Modified |
| `backend/tools.py` | Mask results | ✅ Modified |
| `frontend/ResultsPanel.tsx` | Decrypt UI | ✅ Modified |

## Quick Test

```bash
# 1. Encrypt test
cd backend
python -c "from encryption import AccountEncryption; acc='50200013729069'; enc=AccountEncryption.encrypt_account_number(acc); ok,dec=AccountEncryption.decrypt_with_code(enc,'judge_code'); print(f'✓ {dec}')"

# 2. API test
curl -X POST http://localhost:8000/decrypt -H 'Content-Type: application/json' \
  -d '{"encrypted_account_number":"...","decryption_code":"judge_code"}'
```

---

**Status**: ✅ Complete and Production-Ready

