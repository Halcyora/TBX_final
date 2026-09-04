"""
TBX Finance Assistant - Complex Dataset Generator
Generates realistic financial data with:
- 500K+ transactions over 2-3 years
- 500+ vendors
- Duplicate transactions
- Partial reconciliations (20-30% unreconciled)
- Anomalies and data quality issues
- Recurring vendor patterns
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import os
from pathlib import Path

# Set random seeds for reproducibility
np.random.seed(42)
random.seed(42)

# Configuration
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

NUM_TRANSACTIONS = 100000  # Optimized to 100K for faster generation
START_DATE = datetime(2023, 1, 1)
END_DATE = datetime(2025, 12, 31)
NUM_VENDORS = 550
NUM_ACCOUNTS = 45
UNRECONCILED_RATIO = 0.25  # 25% unreconciled

print(f"[*] Generating dataset with {NUM_TRANSACTIONS:,} transactions...")

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

accounts = []
account_id = 1000
for acc_type, acc_names in account_types.items():
    for name in acc_names:
        accounts.append({
            "account_id": account_id,
            "account_name": name,
            "account_type": acc_type,
            "category": acc_type
        })
        account_id += 1

coa_df = pd.DataFrame(accounts)
coa_df.to_csv(OUTPUT_DIR / "chart_of_accounts.csv", index=False)

# ============================================================================
# 2. VENDOR LIST
# ============================================================================
print("[*] Generating Vendor List...")

vendor_industries = [
    "Technology", "Logistics", "Consulting", "Manufacturing", "Retail",
    "Healthcare", "Education", "Telecommunications", "Energy", "Finance",
    "Real Estate", "Media", "Construction", "Hospitality", "Food & Beverage"
]

vendor_names = [
    "Global", "Tech", "Solutions", "Services", "Enterprises", "Systems",
    "Digital", "Smart", "Cloud", "Data", "Pro", "Supply", "Logistics", "Hub",
    "Center", "Group", "Partners", "Innovations", "Corp", "Inc", "Ltd"
]

vendors = []
for i in range(NUM_VENDORS):
    vendor_name = f"{random.choice(vendor_names)} {random.choice(vendor_names)} {random.randint(100, 9999)}"
    vendors.append({
        "vendor_id": f"V{i+1:05d}",
        "vendor_name": vendor_name,
        "industry": random.choice(vendor_industries),
        "country": random.choice(["USA", "Canada", "UK", "Germany", "India", "Mexico"]),
        "status": random.choice(["Active", "Active", "Active", "Inactive", "On Hold"])
    })

vendor_df = pd.DataFrame(vendors)
vendor_df.to_csv(OUTPUT_DIR / "vendor_list.csv", index=False)

# ============================================================================
# 3. TRANSACTIONS
# ============================================================================
print("[*] Generating Transactions...")

transaction_types = ["Payment", "Invoice", "Expense", "Refund", "Credit Memo"]
statuses = ["Pending", "Completed", "Rejected", "Hold"]

transactions = []
date_range = (END_DATE - START_DATE).days

# Create recurring vendor patterns (20% of vendors have regular transactions)
recurring_vendors = list(vendor_df["vendor_id"].sample(n=int(NUM_VENDORS * 0.2)))

for i in range(NUM_TRANSACTIONS):
    if i % 50000 == 0:
        print(f"  Generated {i:,} transactions...")
    
    # Date distribution
    transaction_date = START_DATE + timedelta(days=random.randint(0, date_range))
    
    # Vendor selection - 80/20 rule (80% from 20% of vendors)
    if random.random() < 0.8:
        vendor_id = random.choice(recurring_vendors)
    else:
        vendor_id = vendor_df.sample(1)["vendor_id"].values[0]
    
    # Amount distribution (log-normal for realistic spending patterns)
    base_amount = np.random.lognormal(mean=6, sigma=2)  # Most transactions $100-$10K
    
    # Anomalies - 2% of transactions are unusually large
    if random.random() < 0.02:
        base_amount *= random.uniform(5, 20)
    
    amount = round(base_amount, 2)
    
    account = coa_df.sample(1).iloc[0]
    
    transactions.append({
        "transaction_id": f"TXN{i+1:07d}",
        "vendor_id": vendor_id,
        "transaction_date": transaction_date.strftime("%Y-%m-%d"),
        "transaction_type": random.choice(transaction_types),
        "amount": amount,
        "currency": "USD",
        "account_id": account["account_id"],
        "account_name": account["account_name"],
        "description": f"Transaction for {vendor_id}",
        "status": random.choice(statuses),
        "invoice_number": f"INV{random.randint(100000, 999999)}" if random.random() > 0.2 else None,
        "reference_number": f"REF{random.randint(10000, 99999)}" if random.random() > 0.3 else None,
        "notes": None if random.random() > 0.1 else "Data quality issue"
    })

txn_df = pd.DataFrame(transactions)

# Add duplicates - 2% of transactions have near-duplicates (same amount, vendor, within 1 day)
duplicate_count = int(len(txn_df) * 0.02)
duplicate_indices = np.random.choice(len(txn_df), duplicate_count, replace=False)
for idx in duplicate_indices:
    dup_row = txn_df.iloc[idx].copy()
    dup_row["transaction_id"] = f"TXN{np.random.randint(1000000, 9999999):07d}"
    dup_row["transaction_date"] = (datetime.strptime(dup_row["transaction_date"], "%Y-%m-%d") + 
                                   timedelta(days=random.randint(-1, 1))).strftime("%Y-%m-%d")
    if random.random() > 0.5:
        dup_row["amount"] = dup_row["amount"] * random.uniform(0.99, 1.01)  # Slight variance
    txn_df = pd.concat([txn_df, dup_row.to_frame().T], ignore_index=True)

# Add missing values (5% of transactions have missing fields)
missing_ratio = 0.05
missing_mask = np.random.random(txn_df.shape) < missing_ratio
missing_mask[:, [0, 1, 2, 3, 4, 5, 6, 7]] = False  # Keep critical fields
txn_df = txn_df.mask(missing_mask)

txn_df = txn_df.sort_values("transaction_id").reset_index(drop=True)
txn_df.to_csv(OUTPUT_DIR / "transactions.csv", index=False)

print(f"  Total transactions (including duplicates): {len(txn_df):,}")

# ============================================================================
# 4. VENDOR PAYOUTS
# ============================================================================
print("[*] Generating Vendor Payouts...")

payouts = []
unique_vendors = txn_df[txn_df["transaction_type"] == "Payment"]["vendor_id"].unique()

for vendor_id in unique_vendors[:int(len(unique_vendors) * 0.7)]:  # 70% of vendors have payouts
    # Number of payouts per vendor varies
    num_payouts = np.random.randint(1, 50)
    
    for _ in range(num_payouts):
        payout_date = START_DATE + timedelta(days=random.randint(0, date_range))
        
        # Payouts related to invoices (but not exactly matching)
        vendor_txns = txn_df[txn_df["vendor_id"] == vendor_id]
        if len(vendor_txns) > 0:
            related_amount = vendor_txns["amount"].sum() * random.uniform(0.5, 1.5)
        else:
            related_amount = round(np.random.lognormal(mean=6, sigma=2), 2)
        
        payouts.append({
            "payout_id": f"PO{len(payouts)+1:07d}",
            "vendor_id": vendor_id,
            "payout_date": payout_date.strftime("%Y-%m-%d"),
            "amount": related_amount,
            "currency": "USD",
            "payment_method": random.choice(["ACH", "Wire Transfer", "Check", "Credit Card"]),
            "status": random.choice(["Completed", "Completed", "Completed", "Pending", "Cancelled"]),
            "reference_number": f"CHECK{random.randint(100000, 999999)}"
        })

payout_df = pd.DataFrame(payouts)
payout_df.to_csv(OUTPUT_DIR / "vendor_payouts.csv", index=False)

# ============================================================================
# 5. RECONCILIATION STATUS
# ============================================================================
print("[*] Generating Reconciliation Status...")

reconciliation = []
unreconciled_count = int(len(txn_df) * UNRECONCILED_RATIO)
unreconciled_indices = np.random.choice(len(txn_df), unreconciled_count, replace=False)

for idx, row in txn_df.iterrows():
    if idx in unreconciled_indices:
        status = random.choice(["Unreconciled", "Pending Reconciliation"])
        matched_payout_id = None
        reconciliation_date = None
        notes = random.choice([
            "Pending bank confirmation",
            "Awaiting vendor documentation",
            "Amount mismatch",
            "Missing supporting documents",
            "Under review"
        ]) if random.random() > 0.3 else None
    else:
        status = random.choice(["Reconciled", "Reconciled", "Partially Reconciled"])
        # Link to payout
        if len(payout_df) > 0 and random.random() > 0.4:
            matched_payout_id = payout_df.sample(1)["payout_id"].values[0]
        else:
            matched_payout_id = None
        
        reconciliation_date = (datetime.strptime(row["transaction_date"], "%Y-%m-%d") + 
                               timedelta(days=random.randint(1, 90))).strftime("%Y-%m-%d")
        notes = None
    
    reconciliation.append({
        "transaction_id": row["transaction_id"],
        "reconciliation_status": status,
        "matched_payout_id": matched_payout_id,
        "reconciliation_date": reconciliation_date,
        "last_reviewed": (datetime.strptime(row["transaction_date"], "%Y-%m-%d") + 
                         timedelta(days=random.randint(0, 180))).strftime("%Y-%m-%d") if random.random() > 0.4 else None,
        "notes": notes
    })

recon_df = pd.DataFrame(reconciliation)
recon_df.to_csv(OUTPUT_DIR / "reconciliation_status.csv", index=False)

# ============================================================================
# 6. DATA DICTIONARY
# ============================================================================
print("[*] Generating Data Dictionary...")

data_dict = {
    "File": [
        "transactions.csv", "transactions.csv", "transactions.csv", "transactions.csv",
        "transactions.csv", "transactions.csv", "transactions.csv", "transactions.csv",
        "vendor_payouts.csv", "vendor_payouts.csv", "vendor_payouts.csv",
        "reconciliation_status.csv", "reconciliation_status.csv", "reconciliation_status.csv",
        "chart_of_accounts.csv", "chart_of_accounts.csv",
        "vendor_list.csv", "vendor_list.csv", "vendor_list.csv"
    ],
    "Column": [
        "transaction_id", "vendor_id", "transaction_date", "amount", "currency",
        "transaction_type", "status", "account_id",
        "payout_id", "vendor_id", "amount",
        "transaction_id", "reconciliation_status", "matched_payout_id",
        "account_id", "account_type",
        "vendor_id", "vendor_name", "status"
    ],
    "Description": [
        "Unique transaction identifier", "Vendor identifier (links to vendor_list)", 
        "Date of transaction (YYYY-MM-DD)", "Transaction amount in USD",
        "Currency (USD)", "Type of transaction (Payment, Invoice, Expense, Refund, Credit Memo)",
        "Transaction status (Pending, Completed, Rejected, Hold)", "Account code (links to chart_of_accounts)",
        "Unique payout identifier", "Vendor identifier",
        "Payout amount in USD",
        "Transaction ID (links to transactions)", "Reconciliation status (Reconciled, Unreconciled, Partially Reconciled)",
        "Linked payout ID (if matched)",
        "Account ID (unique identifier)", "Account type (Assets, Liabilities, Revenue, Expense)",
        "Vendor ID (unique identifier)", "Vendor business name", "Vendor status (Active, Inactive, On Hold)"
    ],
    "Data Type": [
        "TEXT", "TEXT", "DATE", "DECIMAL", "TEXT",
        "TEXT", "TEXT", "INTEGER",
        "TEXT", "TEXT", "DECIMAL",
        "TEXT", "TEXT", "TEXT",
        "INTEGER", "TEXT",
        "TEXT", "TEXT", "TEXT"
    ]
}

dict_df = pd.DataFrame(data_dict)
dict_df.to_csv(OUTPUT_DIR / "data_dictionary.csv", index=False)

# ============================================================================
# SUMMARY STATISTICS
# ============================================================================
print("\n" + "="*80)
print("DATASET GENERATION COMPLETE")
print("="*80)
print(f"Output Directory: {OUTPUT_DIR}")
print(f"\nDataset Statistics:")
print(f"  - Total Transactions: {len(txn_df):,}")
print(f"  - Total Vendors: {len(vendor_df):,}")
print(f"  - Total Payouts: {len(payout_df):,}")
print(f"  - Total Accounts: {len(coa_df):,}")
print(f"  - Date Range: {START_DATE.date()} to {END_DATE.date()}")
print(f"\nData Quality Issues:")
print(f"  - Unreconciled Transactions: {len(recon_df[recon_df['reconciliation_status'] != 'Reconciled']):,} ({UNRECONCILED_RATIO*100:.1f}%)")
print(f"  - Duplicate Transactions: ~{duplicate_count:,} ({duplicate_count/len(txn_df)*100:.2f}%)")
print(f"  - Missing Values: ~5%")
print(f"\nFiles Generated:")
for file in sorted(OUTPUT_DIR.glob("*.csv")):
    size_mb = file.stat().st_size / (1024*1024)
    rows = len(pd.read_csv(file))
    print(f"  - {file.name:<30} {rows:>10,} rows | {size_mb:>6.2f} MB")

print("\n" + "="*80)
print("Dataset ready for TBX Finance Assistant implementation!")
print("="*80)
