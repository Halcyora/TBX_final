# TBX Finance Assistant - Dataset Integration

## Current Status ✅

**Active Dataset**: Small (10 records - easy verification)
- **Location**: `data/`
- **Records**: 10 banks, 10 accounts, 10 transactions
- **Database**: DuckDB at `data/finance.db`
- **Status**: ✓ Fully ingested and queryable

## Dataset Structure

### Small Dataset (`data/small/` + `data/`)
```
bank.csv:        10 canonical Indian banks (HDFC, ICIC, SBIN, etc.)
account.csv:     10 accounts with various balance states (negative, positive, large)
transaction.csv: 10 transactions (mix of debit/credit) with edge cases
```

### Large Dataset (`data/large/`)
```
bank.csv:        50 banks (expanded Indian financial institutions)
account.csv:     10,000 accounts (various program IDs: 0, 4, 21, 46, 99)
transaction.csv: 507,200+ transactions (includes all 10 small + edge cases)
```

## Edge Cases in Large Dataset

- **Null/Empty Fields**: 174,938 NULL UTRs (~35%), 100,120 NULL reference_ids (~20%)
- **Amount Edge Cases**: 10,181 zero-amount txns, micro amounts (0.01), extreme values (999M+)
- **Special Characters**: SQL patterns, quotes, slashes, tabs, newlines, Unicode (₹, &, @)
- **Duplicate References**: Shared transaction_reference_id and UTR across accounts
- **Encrypted UTRs**: Base64/AES format strings (~60% of UTRs)
- **Timestamp Precision**: Microsecond precision, leap day (2024-02-29), year boundaries

## Switching Datasets

### In Python Code:

```python
from backend.database import FinanceDB

# Load small dataset (default)
db = FinanceDB(dataset="small")

# Load large dataset
db = FinanceDB(dataset="large")

# Switch at runtime
db.switch_dataset("large")

# Get dataset stats
stats = db.get_dataset_stats()
print(f"Transactions: {stats['transaction_count']:,}")
```

### Programmatic Examples:

```python
# Query across bank → account → transaction
result = db.execute_query("""
    SELECT 
        b.bank_name,
        a.account_number,
        t.transaction_type,
        COUNT(*) as txn_count
    FROM account a
    JOIN bank b ON a.bank_code = b.bank_code
    JOIN transaction t ON a.account_id = t.account_id
    GROUP BY b.bank_name, a.account_number, t.transaction_type
""")

# Find transactions with missing UTRs
result = db.execute_query("""
    SELECT COUNT(*) as missing_utrs
    FROM transaction
    WHERE utr_number = ''
""")

# Account balance distribution
result = db.execute_query("""
    SELECT 
        CASE WHEN CAST(available_balance AS DECIMAL) < 0 THEN 'Negative'
             WHEN available_balance = '0.00' THEN 'Zero'
             ELSE 'Positive' END as balance_type,
        COUNT(*) as count
    FROM account
    GROUP BY balance_type
""")
```

## TBX Schema

### `bank`
| Column | Type | Notes |
|--------|------|-------|
| `bank_code` | VARCHAR | Primary key (e.g., HDFC, ICIC, SBIN) |
| `bank_name` | VARCHAR | Canonical bank name |

### `account`
| Column | Type | Notes |
|--------|------|-------|
| `account_id` | VARCHAR | Primary key (UUID) |
| `entity_id` | VARCHAR | Entity/customer ID (UUID) |
| `account_number` | VARCHAR | Sensitive - should mask in output |
| `program_id` | VARCHAR | Program/product ID (0, 4, 21, 46, 99) |
| `available_balance` | VARCHAR | Balance (can be negative) |
| `bank_code` | VARCHAR | Foreign key → bank.bank_code |

### `transaction`
| Column | Type | Notes |
|--------|------|-------|
| `transaction_id` | VARCHAR | Primary key (UUID) |
| `account_id` | VARCHAR | Foreign key → account.account_id |
| `transaction_date` | VARCHAR | Timestamp with microsecond precision |
| `transaction_type` | VARCHAR | 'debit' or 'credit' |
| `description` | VARCHAR | Transaction description (can contain special chars) |
| `transaction_amount` | VARCHAR | Amount (can be 0.00, 0.01, or extreme values) |
| `transaction_reference_id` | VARCHAR | Reference number (often empty) |
| `utr_number` | VARCHAR | Unique transaction reference (often empty, encrypted, or shared) |

## Database Operations

### List all tables and columns:
```python
schema = db.get_schema_info()
for table, columns in schema.items():
    print(f"{table}: {columns}")
```

### Get dataset statistics:
```python
stats = db.get_dataset_stats()
print(f"Banks: {stats['bank_count']}")
print(f"Accounts: {stats['account_count']}")
print(f"Transactions: {stats['transaction_count']:,}")
print(f"Total balance: ${stats['total_balance']:.2f}")
```

### Close database:
```python
db.close()
```

## Files & Directories

```
data/
├── bank.csv              # Small dataset (10 banks)
├── account.csv           # Small dataset (10 accounts)
├── transaction.csv       # Small dataset (10 transactions)
├── finance.db            # DuckDB database file
├── small/
│   ├── bank.csv
│   ├── account.csv
│   └── transaction.csv
└── large/
    ├── bank.csv          # 50 banks
    ├── account.csv       # 10,000 accounts
    └── transaction.csv   # 507,200+ transactions

backend/
└── database.py           # FinanceDB class with dataset switching

generate_tbx_datasets.py  # Dataset generator script
verify_small_dataset.py   # Verification script
cleanup_old_dataset.py    # Cleanup helper
```

## Next Steps

1. **Verify Small Dataset**: ✅ Done
2. **Test With Large Dataset**:
   ```python
   db_large = FinanceDB(dataset="large")
   stats = db_large.get_dataset_stats()
   ```
3. **Integrate with Backend/Frontend**: Update API endpoints to use new schema
4. **Update SQL Validator & Prompts**: Align with bank/account/transaction schema
5. **Run Full Integration Tests**: Validate with LLM pipelines

---

**Last Updated**: 2026-09-05
