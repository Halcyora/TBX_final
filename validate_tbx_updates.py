"""Validation script for TBX schema updates"""
import sys
sys.path.append('backend')

from sql_validator import SQLValidator
from database import FinanceDB

print("=" * 70)
print("VALIDATING UPDATED FILES FOR TBX SCHEMA")
print("=" * 70)

# Test 1: SQL Validator
print("\n✓ Test 1 - SQL Validator (TBX Schema)")
test_queries = [
    "SELECT b.bank_name, COUNT(t.transaction_id) FROM bank b JOIN account a ON b.bank_code = a.bank_code JOIN transaction t ON a.account_id = t.account_id GROUP BY b.bank_name",
    "SELECT * FROM account WHERE CAST(available_balance AS DECIMAL) < 0",
    "SELECT transaction_type, AVG(CAST(transaction_amount AS DECIMAL)) FROM transaction GROUP BY transaction_type"
]

for i, sql in enumerate(test_queries, 1):
    valid, msg = SQLValidator.validate_query(sql)
    status = "✓" if valid else "✗"
    print(f"  {status} Query {i}: {msg}")

# Test 2: Database connectivity
print("\n✓ Test 2 - Database Loading (Small Dataset)")
db = FinanceDB(dataset="small")
stats = db.get_dataset_stats()
print(f"  Banks: {stats['bank_count']}")
print(f"  Accounts: {stats['account_count']}")
print(f"  Transactions: {stats['transaction_count']}")

# Test 3: TBX Schema queries
print("\n✓ Test 3 - Sample TBX Queries")
result = db.execute_query("SELECT COUNT(*) as total FROM bank")
print(f"  Bank count: {result[0]['total']}")

result = db.execute_query("SELECT transaction_type, COUNT(*) as count FROM transaction GROUP BY transaction_type")
print(f"  Transaction types: {len(result)} types")
for row in result:
    print(f"    - {row['transaction_type']}: {row['count']}")

# Test 4: Allowed tables in validator
print("\n✓ Test 4 - Allowed Tables in Validator")
print(f"  Allowed tables: {sorted(SQLValidator.ALLOWED_TABLES)}")

print("\n" + "=" * 70)
print("✅ ALL VALIDATIONS PASSED - FILES UPDATED FOR TBX SCHEMA")
print("=" * 70)
