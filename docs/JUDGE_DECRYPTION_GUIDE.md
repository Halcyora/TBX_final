# Judge/Evaluator Quick Reference: Account Number Decryption

**See full guide**: [ACCOUNT_ENCRYPTION.md](ACCOUNT_ENCRYPTION.md)

## Your Decryption Code

```
judge_code
```

(If different, it will be provided separately)

## Quick Start

### Option 1: Using Frontend

1. Ask a question: "Show balance for account X"
2. See masked result: `****3729069`
3. Scroll down to "Decryption Panel"
4. Enter code: `judge_code`
5. Click "🔒 Decrypt" button
6. Full account number revealed ✅

### Option 2: Using API (cURL)

```bash
# 1. Get encrypted value from query results
# (copy the account_number_encrypted field)

# 2. Decrypt
curl -X POST http://localhost:8000/decrypt \
  -H "Content-Type: application/json" \
  -d '{
    "encrypted_account_number": "gAAAAABl9sX5Rk3JqPa7...",
    "decryption_code": "judge_code"
  }'

# Response:
# {"success": true, "account_number": "50200013729069"}
```

### Option 3: Using Python

```python
import requests

response = requests.post(
    'http://localhost:8000/decrypt',
    json={
        'encrypted_account_number': 'gAAAAABl9sX5Rk3JqPa7...',
        'decryption_code': 'judge_code'
    }
)
print(response.json())
# {'success': True, 'account_number': '50200013729069'}
```

## Common Queries

```
"List all accounts"
"Show balance for account 50200013729069"
"Which accounts have negative balances?"
"All accounts at HDFC BANK LIMITED"
"Transactions from Q3 2025"
```

## Sample Workflow

### Scenario: Verify Account Balances

```
1. Query: "Show all accounts with balance > $10,000"
   ↓ Results:
   Bank: HDFC BANK LIMITED
   Account: ****3729069  [Decrypt]
   Balance: $50,000.00

2. Click [Decrypt] → Enter "judge_code"
   ↓ Success:
   Account: 50200013729069  ✅

3. Verify in external system → Confirmed ✅
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `"Invalid decryption code"` | Check code spelling (case-sensitive) |
| `"Failed to decrypt"` | Try a fresh query result |
| No decrypt button visible | Query results have no encrypted accounts |
| Decryption panel not showing | Scroll down, panel is at bottom |

## Response Formats

### Decrypt Success
```json
{
  "success": true,
  "account_number": "50200013729069",
  "error": null
}
```

### Decrypt Failed
```json
{
  "success": false,
  "account_number": null,
  "error": "Invalid decryption code"
}
```

## Tips

✅ Same code works for all encrypted values  
✅ Decrypt multiple rows one at a time  
✅ Press Enter in input field to trigger decrypt  
✅ Copy-paste encrypted values carefully  
✅ Results include masked AND encrypted values  

## Need Help?

- **Technical Details**: See [ACCOUNT_ENCRYPTION.md](ACCOUNT_ENCRYPTION.md)
- **API Reference**: See [README.md](README.md#security-feature-account-number-encryption)
- **Setup Issues**: Check `.env` has `DECRYPTION_CODES=judge_code`

---

**System Status**: ✅ Ready for Evaluation

