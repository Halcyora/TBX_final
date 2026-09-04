"""
TBX Finance Assistant - Optimized Dataset Generator
Generates realistic financial data efficiently
- 100K transactions over 2-3 years
- 550 vendors
- Duplicates, partial reconciliations, anomalies, missing values
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path
import math

# Configuration
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

NUM_TRANSACTIONS = 100000
START_DATE = datetime(2023, 1, 1)
END_DATE = datetime(2025, 12, 31)
NUM_VENDORS = 550
UNRECONCILED_RATIO = 0.25

random.seed(42)

print("[*] Generating dataset optimized version...")
print(f"    Target: {NUM_TRANSACTIONS:,} transactions, {NUM_VENDORS} vendors")

# ============================================================================
# 1. CHART OF ACCOUNTS
# ============================================================================
print("[*] Generating Chart of Accounts...")

account_types = {
    "Assets": ["Cash", "Accounts Receivable", "Inventory", "Equipment", "Prepaid Expenses"],
    "Liabilities": ["Accounts Payable", "Short-term Debt", "Long-term Debt", "Accrued Expenses"],
    "Equity": ["Common Stock", "Retained Earnings", "Additional Paid-in Capital"],
    "Revenue": ["Product Sales", "Service Revenue", "Subscription Revenue", "Consulting"],
    "Expenses": [
        "Salaries & Wages", "Rent", "Utilities", "Office Supplies", "Travel",
        "Marketing", "Maintenance", "Insurance", "Professional Services",
        "Depreciation", "Vendor Payments", "Payroll Tax", "Benefits",
        "Shipping & Logistics", "Research & Development", "Software Licenses"
    ]
}

with open(OUTPUT_DIR / "chart_of_accounts.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["account_id", "account_name", "account_type", "category"])
    account_id = 1000
    accounts = []
    for acc_type, acc_names in account_types.items():
        for name in acc_names:
            writer.writerow([account_id, name, acc_type, acc_type])
            accounts.append((account_id, name, acc_type))
            account_id += 1

# ============================================================================
# 2. VENDOR LIST
# ============================================================================
print("[*] Generating Vendor List...")

vendor_industries = [
    "Technology", "Logistics", "Consulting", "Manufacturing", "Retail",
    "Healthcare", "Education", "Telecommunications", "Energy", "Finance",
]

vendor_names_words = [
    "Global", "Tech", "Solutions", "Services", "Enterprises", "Systems",
    "Digital", "Smart", "Cloud", "Data", "Pro", "Supply", "Hub", "Center"
]

with open(OUTPUT_DIR / "vendor_list.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["vendor_id", "vendor_name", "industry", "country", "status"])
    vendors = []
    for i in range(NUM_VENDORS):
        vendor_name = f"{random.choice(vendor_names_words)} {random.choice(vendor_names_words)} {random.randint(100, 9999)}"
        vendor_id = f"V{i+1:05d}"
        writer.writerow([
            vendor_id,
            vendor_name,
            random.choice(vendor_industries),
            random.choice(["USA", "Canada", "UK", "Germany", "India"]),
            random.choice(["Active", "Active", "Active", "Inactive", "On Hold"])
        ])
        vendors.append(vendor_id)

# ============================================================================
# 3. TRANSACTIONS (Direct CSV write)
# ============================================================================
print("[*] Generating Transactions...")

date_range_days = (END_DATE - START_DATE).days
recurring_vendors = set(random.sample(vendors, int(NUM_VENDORS * 0.2)))
transactions_written = 0

with open(OUTPUT_DIR / "transactions.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        "transaction_id", "vendor_id", "transaction_date", "transaction_type",
        "amount", "currency", "account_id", "account_name", "description",
        "status", "invoice_number", "reference_number", "notes"
    ])
    
    transaction_ids = []
    for i in range(NUM_TRANSACTIONS):
        if i % 20000 == 0 and i > 0:
            print(f"  Generated {i:,} transactions...")
        
        # Date
        tx_date = START_DATE + timedelta(days=random.randint(0, date_range_days))
        
        # Vendor (80/20 rule)
        if random.random() < 0.8:
            vendor_id = random.choice(list(recurring_vendors))
        else:
            vendor_id = random.choice(vendors)
        
        # Amount (log-normal distribution)
        amount = math.exp(random.gauss(6, 2))
        if random.random() < 0.02:  # 2% anomalies
            amount *= random.uniform(5, 20)
        amount = round(amount, 2)
        
        # Account
        account = random.choice(accounts)
        
        transaction_id = f"TXN{i+1:07d}"
        transaction_ids.append(transaction_id)
        
        writer.writerow([
            transaction_id,
            vendor_id,
            tx_date.strftime("%Y-%m-%d"),
            random.choice(["Payment", "Invoice", "Expense", "Refund", "Credit Memo"]),
            amount,
            "USD",
            account[0],
            account[1],
            f"Transaction for {vendor_id}",
            random.choice(["Pending", "Completed", "Rejected", "Hold"]),
            f"INV{random.randint(100000, 999999)}" if random.random() > 0.2 else "",
            f"REF{random.randint(10000, 99999)}" if random.random() > 0.3 else "",
            "Data quality issue" if random.random() < 0.1 else ""
        ])
        
        transactions_written += 1

print(f"  Total transactions: {transactions_written:,}")

# ============================================================================
# 4. VENDOR PAYOUTS
# ============================================================================
print("[*] Generating Vendor Payouts...")

with open(OUTPUT_DIR / "vendor_payouts.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["payout_id", "vendor_id", "payout_date", "amount", "currency",
                     "payment_method", "status", "reference_number"])
    
    payout_id = 1
    for vendor in random.sample(vendors, int(len(vendors) * 0.7)):
        num_payouts = random.randint(1, 30)
        for _ in range(num_payouts):
            payout_date = START_DATE + timedelta(days=random.randint(0, date_range_days))
            amount = round(math.exp(random.gauss(6, 2)), 2)
            
            writer.writerow([
                f"PO{payout_id:07d}",
                vendor,
                payout_date.strftime("%Y-%m-%d"),
                amount,
                "USD",
                random.choice(["ACH", "Wire Transfer", "Check", "Credit Card"]),
                random.choice(["Completed", "Completed", "Completed", "Pending", "Cancelled"]),
                f"CHECK{random.randint(100000, 999999)}"
            ])
            payout_id += 1

# ============================================================================
# 5. RECONCILIATION STATUS
# ============================================================================
print("[*] Generating Reconciliation Status...")

unreconciled_ids = set(random.sample(range(NUM_TRANSACTIONS), 
                                     int(NUM_TRANSACTIONS * UNRECONCILED_RATIO)))

with open(OUTPUT_DIR / "reconciliation_status.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["transaction_id", "reconciliation_status", "matched_payout_id",
                     "reconciliation_date", "last_reviewed", "notes"])
    
    for idx in range(NUM_TRANSACTIONS):
        transaction_id = f"TXN{idx+1:07d}"
        
        if idx in unreconciled_ids:
            status = random.choice(["Unreconciled", "Pending Reconciliation"])
            matched_payout = ""
            recon_date = ""
            notes = random.choice([
                "Pending bank confirmation", "Awaiting vendor documentation",
                "Amount mismatch", "Missing supporting documents"
            ]) if random.random() > 0.3 else ""
        else:
            status = random.choice(["Reconciled", "Reconciled", "Partially Reconciled"])
            matched_payout = f"PO{random.randint(1, 100000):07d}" if random.random() > 0.4 else ""
            recon_date = (START_DATE + timedelta(days=random.randint(0, date_range_days))).strftime("%Y-%m-%d")
            notes = ""
        
        last_reviewed = (START_DATE + timedelta(days=random.randint(0, date_range_days))).strftime("%Y-%m-%d") \
                        if random.random() > 0.4 else ""
        
        writer.writerow([
            transaction_id,
            status,
            matched_payout,
            recon_date,
            last_reviewed,
            notes
        ])

# ============================================================================
# 6. DATA DICTIONARY
# ============================================================================
print("[*] Generating Data Dictionary...")

data_dict_rows = [
    ["transactions.csv", "transaction_id", "Unique transaction identifier", "TEXT"],
    ["transactions.csv", "vendor_id", "Vendor identifier (links to vendor_list)", "TEXT"],
    ["transactions.csv", "transaction_date", "Date of transaction (YYYY-MM-DD)", "DATE"],
    ["transactions.csv", "amount", "Transaction amount in USD", "DECIMAL"],
    ["transactions.csv", "currency", "Currency (USD)", "TEXT"],
    ["transactions.csv", "transaction_type", "Type (Payment, Invoice, Expense, Refund)", "TEXT"],
    ["transactions.csv", "status", "Status (Pending, Completed, Rejected, Hold)", "TEXT"],
    ["vendor_payouts.csv", "payout_id", "Unique payout identifier", "TEXT"],
    ["vendor_payouts.csv", "vendor_id", "Vendor identifier", "TEXT"],
    ["vendor_payouts.csv", "amount", "Payout amount in USD", "DECIMAL"],
    ["reconciliation_status.csv", "transaction_id", "Transaction ID", "TEXT"],
    ["reconciliation_status.csv", "reconciliation_status", "Status (Reconciled, Unreconciled)", "TEXT"],
    ["chart_of_accounts.csv", "account_id", "Account ID (unique identifier)", "INTEGER"],
    ["chart_of_accounts.csv", "account_type", "Account type (Assets, Liabilities, Revenue, Expense)", "TEXT"],
    ["vendor_list.csv", "vendor_id", "Vendor ID", "TEXT"],
    ["vendor_list.csv", "vendor_name", "Vendor business name", "TEXT"],
    ["vendor_list.csv", "status", "Status (Active, Inactive, On Hold)", "TEXT"],
]

with open(OUTPUT_DIR / "data_dictionary.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["File", "Column", "Description", "Data Type"])
    writer.writerows(data_dict_rows)

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "="*80)
print("DATASET GENERATION COMPLETE!")
print("="*80)

import os
for file in sorted(OUTPUT_DIR.glob("*.csv")):
    size_mb = os.path.getsize(file) / (1024*1024)
    print(f"  {file.name:<30} {size_mb:>6.2f} MB")

print("\n" + "="*80)
print("Complex Financial Dataset Ready!")
print("="*80)
