"""
TBX Finance Assistant - Small & Large Dataset Generator
Schema based strictly on `TBX - Database Schema.md`:
  - `bank`: bank_code, bank_name
  - `account`: account_id, entity_id, account_number, program_id, available_balance, bank_code
  - `transaction`: transaction_id, account_id, transaction_date, transaction_type, description, transaction_amount, transaction_reference_id, utr_number

Data Specifications:
  - Small dataset: Exactly 10 records per table from schema sample data. Saved in `data/small/`.
  - Large dataset: 500,000 transactions, ~10,000 accounts, 50 banks. Includes all 10 records from the small dataset.
    Loaded with realistic financial edge cases:
      - Null/Missing transaction_reference_id and utr_number
      - Zero, negative, micro, and extreme large amounts/balances
      - Complex descriptions: quotes, slashes, tabs, multi-line/newlines, non-ASCII characters, SQL-injection patterns, extra whitespace
      - Duplicate reference IDs and UTR numbers across different accounts and transaction types
      - Encrypted UTR strings (Base64/AES format) & plaintext UTRs
      - Timestamps with microseconds, leap day (2024-02-29), year-end/new-year boundaries
"""

import csv
import uuid
import random
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add backend to path for importing encryption module
sys.path.insert(0, str(Path(__file__).parent / "backend"))
from encryption import AccountEncryption

# Paths
BASE_DIR = Path(__file__).parent
SMALL_DIR = BASE_DIR / "data" / "small"
LARGE_DIR = BASE_DIR / "data" / "large"

SMALL_DIR.mkdir(parents=True, exist_ok=True)
LARGE_DIR.mkdir(parents=True, exist_ok=True)

random.seed(42)

# ============================================================================
# SMALL DATASET (Exact 10 records from TBX - Database Schema.md)
# ============================================================================

SMALL_BANKS = [
    {"bank_code": "HDFC", "bank_name": "HDFC BANK LIMITED"},
    {"bank_code": "ICIC", "bank_name": "ICICI BANK LIMITED"},
    {"bank_code": "SBIN", "bank_name": "STATE BANK OF INDIA"},
    {"bank_code": "UTIB", "bank_name": "AXIS BANK LIMITED"},
    {"bank_code": "KKBK", "bank_name": "KOTAK MAHINDRA BANK LIMITED"},
    {"bank_code": "CNRB", "bank_name": "CANARA BANK"},
    {"bank_code": "UBIN", "bank_name": "UNION BANK OF INDIA"},
    {"bank_code": "AUBL", "bank_name": "AU SMALL FINANCE BANK LIMITED"},
    {"bank_code": "TMBL", "bank_name": "TAMILNAD MERCANTILE BANK LIMITED"},
    {"bank_code": "RATN", "bank_name": "RBL BANK LIMITED"},
]

SMALL_ACCOUNTS = [
    {"account_id": "acfbe204-7541-492c-a352-040aa984bedc", "entity_id": "f2f5e332-c2d1-4555-9a6b-65c7cd195077", "account_number": "50200013729069", "program_id": 21, "available_balance": -25907487.00, "bank_code": "HDFC"},
    {"account_id": "6f306737-dfa8-4bf7-8003-be64034b8dea", "entity_id": "2d52dda2-d98a-4381-af80-45bdb173860c", "account_number": "50200099284137", "program_id": 21, "available_balance": -94766029.00, "bank_code": "HDFC"},
    {"account_id": "bfbfe347-11d6-48d7-acff-4f091f59d34b", "entity_id": "e767c3c1-3a0d-43b5-b2ff-06f49bdf3de2", "account_number": "39208809622308", "program_id": 4,  "available_balance": 40842693.08,  "bank_code": "UBIN"},
    {"account_id": "212239b5-63d9-4da6-aa8c-46485e0f8a42", "entity_id": "ac1a0654-461b-4216-95d1-bbcb9ab6da4e", "account_number": "30123456789012", "program_id": 46, "available_balance": 109283.80,   "bank_code": "SBIN"},
    {"account_id": "34448e78-c3fe-4b5d-be8c-a45a6349b8d4", "entity_id": "e984c75d-aad6-4655-823a-4e9e06a869bc", "account_number": "40100556677889", "program_id": 21, "available_balance": 231680596.77, "bank_code": "UTIB"},
    {"account_id": "5cecd2c2-f075-4bbd-a08b-b156ca48dc7e", "entity_id": "e0000005-0000-0000-0000-000000000005", "account_number": "60100112233445", "program_id": 4,  "available_balance": -131629423.33,"bank_code": "HDFC"},
    {"account_id": "e767c3c1-3a0d-43b5-b2ff-06f49bdf3de2", "entity_id": "00000006-0000-0000-0000-000000000006", "account_number": "70100334455667", "program_id": 21, "available_balance": 8695000.75,   "bank_code": "KKBK"},
    {"account_id": "2d52dda2-d98a-4381-af80-45bdb173860c", "entity_id": "00000007-0000-0000-0000-000000000007", "account_number": "80100123456789", "program_id": 46, "available_balance": 3887946.81,   "bank_code": "CNRB"},
    {"account_id": "ac1a0654-461b-4216-95d1-bbcb9ab6da4e", "entity_id": "00000008-0000-0000-0000-000000000008", "account_number": "90100987654321", "program_id": 21, "available_balance": 3278516.63,   "bank_code": "SBIN"},
    {"account_id": "e984c75d-aad6-4655-823a-4e9e06a869bc", "entity_id": "00000009-0000-0000-0000-000000000009", "account_number": "20100556677889", "program_id": 46, "available_balance": -117420771.35,"bank_code": "ICIC"},
]

SMALL_TRANSACTIONS = [
    {
        "transaction_id": "001cb576-eb28-44b1-a219-0f3f27093fad",
        "account_id": "acfbe204-7541-492c-a352-040aa984bedc",
        "transaction_date": "2026-06-24 18:24:06.000000",
        "transaction_type": "debit",
        "description": "FT -  95842568 -  50200013729069 - SELECTION ELECTRONICS   DAHISAR EAST",
        "transaction_amount": 14866.00,
        "transaction_reference_id": "1715499972",
        "utr_number": "jhI5nAdyb1qOEjmcB3JvWjC6tTO+ZPVqBFPm/GiErC4TRBWRQ5ylPG3p"
    },
    {
        "transaction_id": "0021433a-8d92-40e9-b811-5ba994747975",
        "account_id": "6f306737-dfa8-4bf7-8003-be64034b8dea",
        "transaction_date": "2026-05-14 11:31:37.000000",
        "transaction_type": "debit",
        "description": "UPI-NAVYUG SELECTION-XXXXXX8672-AUBL0002125-103293775381-260514201735136",
        "transaction_amount": 50000.00,
        "transaction_reference_id": "103293775381",
        "utr_number": "jhI5nAdyb1qOEjmcB3JvWjC9tzSzbvtkBlK+NSqsiL164ZK8Bl8cYg8y1l8="
    },
    {
        "transaction_id": "00baf475-8710-4d17-b626-d25fc311eb7f",
        "account_id": "5cecd2c2-f075-4bbd-a08b-b156ca48dc7e",
        "transaction_date": "2025-12-16 18:13:34.000000",
        "transaction_type": "credit",
        "description": "R/RATNR52025121600100235/ZBFLCTP405PBL15667333//SELECTRICITY TWO PRIVATE LIMITED/RATNR52025121600100235 /SELECTRICITY TWO PRIVATE LIMITED",
        "transaction_amount": 260000.00,
        "transaction_reference_id": "S31125841",
        "utr_number": ""
    },
    {
        "transaction_id": "014b7179-e696-4837-9b8e-7164d171b760",
        "account_id": "acfbe204-7541-492c-a352-040aa984bedc",
        "transaction_date": "2026-06-24 06:39:10.000000",
        "transaction_type": "debit",
        "description": "NEFT  - UTIB0002678 - 95604250 - 915020031685136 - UMANG SELECTIONHAPURBPES DPF10129",
        "transaction_amount": 7959.00,
        "transaction_reference_id": "HDFCH01078329532",
        "utr_number": "jhI5nAdyb1qOEjmcB3JvWknJwkXCbf1jBFm1NhmQqR0EoF/PNGRDCa1+UTH2I/tV"
    },
    {
        "transaction_id": "000000ac-39c5-4eb3-9fe3-ed40ceecee5d",
        "account_id": "e984c75d-aad6-4655-823a-4e9e06a869bc",
        "transaction_date": "2025-12-03 16:24:54.000000",
        "transaction_type": "debit",
        "description": "NEFT/000483399203/ICIC/PARESH VIKRANT GHASE",
        "transaction_amount": 9241.00,
        "transaction_reference_id": "S5314253",
        "utr_number": ""
    },
    {
        "transaction_id": "04818df6-e726-4405-a8e3-4f6c15caa956",
        "account_id": "e767c3c1-3a0d-43b5-b2ff-06f49bdf3de2",
        "transaction_date": "2026-01-02 09:58:41.000000",
        "transaction_type": "credit",
        "description": "IMPS/P2A/600228462725/UTIB/918020101986700/00/INET/9211/SELECTIONMALIGAI/ZBFLCTP5L2PBL11476675/INWD48",
        "transaction_amount": 36810.00,
        "transaction_reference_id": "S69244711",
        "utr_number": ""
    },
    {
        "transaction_id": "0178b656-4a7d-98e8-9540f6e24caf",
        "account_id": "ac1a0654-461b-4216-95d1-bbcb9ab6da4e",
        "transaction_date": "2026-03-17 14:53:45.000000",
        "transaction_type": "debit",
        "description": "IMPS OW/507614422198/Gautam singh/SBIN/43292707719",
        "transaction_amount": 110.00,
        "transaction_reference_id": "",
        "utr_number": ""
    },
    {
        "transaction_id": "0266384b-929c-478d-a7da-a54acf984343",
        "account_id": "acfbe204-7541-492c-a352-040aa984bedc",
        "transaction_date": "2026-06-24 06:30:27.000000",
        "transaction_type": "debit",
        "description": "NEFT  - ICIC0001241 - 95584112 - 124105002702 - SELECTION MOBILE",
        "transaction_amount": 66899.00,
        "transaction_reference_id": "HDFCH01078324740",
        "utr_number": "jhI5nAdyb1qOEjmcB3JvWknJwkXCbf1jBFm1NhSSrh+QRpxgqe0VEdKaiI24S8Up"
    },
    {
        "transaction_id": "02c96198-4397-4160-b5ce-607f6696f581",
        "account_id": "acfbe204-7541-492c-a352-040aa984bedc",
        "transaction_date": "2026-06-24 06:56:01.000000",
        "transaction_type": "debit",
        "description": "NEFT  - ICIC0001241 - 95600270 - 124105002702 - SELECTION MOBILE",
        "transaction_amount": 79575.00,
        "transaction_reference_id": "HDFCH01078342174",
        "utr_number": "jhI5nAdyb1qOEjmcB3JvWknJwkXCbf1jBFm1MBKUrRvYyGUaTtHlT1wi23x31CRl"
    },
    {
        "transaction_id": "038969bd-5941-4d13-ba9f-dda911cc0b4e",
        "account_id": "6f306737-dfa8-4bf7-8003-be64034b8dea",
        "transaction_date": "2026-05-20 09:49:02.000000",
        "transaction_type": "debit",
        "description": "FT-RERELI2010000810-RELIANCEDIGITAL RETAIL LTD   SELECT CITY SAKET DELHI",
        "transaction_amount": 21156.00,
        "transaction_reference_id": "1643797818",
        "utr_number": "jhI5nAdyb1qOEjmcB3JvWjC7sDW9ZPtrAllbY+gS/wWLLijTRu8nX6op"
    }
]

def write_small_dataset():
    print("[*] Writing Small Dataset (data/small)...")
    
    with open(SMALL_DIR / "bank.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bank_code", "bank_name"])
        for b in SMALL_BANKS:
            w.writerow([b["bank_code"], b["bank_name"]])
            
    with open(SMALL_DIR / "account.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["account_id", "entity_id", "account_number", "program_id", "available_balance", "bank_code"])
        for a in SMALL_ACCOUNTS:
            w.writerow([a["account_id"], a["entity_id"], a["account_number"], a["program_id"], f"{a['available_balance']:.2f}", a["bank_code"]])
            
    with open(SMALL_DIR / "transaction.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["transaction_id", "account_id", "transaction_date", "transaction_type", "description", "transaction_amount", "transaction_reference_id", "utr_number"])
        for t in SMALL_TRANSACTIONS:
            w.writerow([
                t["transaction_id"], t["account_id"], t["transaction_date"], t["transaction_type"],
                t["description"], f"{t['transaction_amount']:.2f}", t["transaction_reference_id"], t["utr_number"]
            ])
            
    # Also write to root data/ folder as current active dataset
    DATA_ROOT = BASE_DIR / "data"
    for filename in ["bank.csv", "account.csv", "transaction.csv"]:
        src = SMALL_DIR / filename
        dst = DATA_ROOT / filename
        dst.write_bytes(src.read_bytes())
    print("[+] Small dataset saved to data/small and ingested into data/")

# ============================================================================
# LARGE DATASET GENERATION (500,000 transactions + 50 banks + 10,000 accounts)
# ============================================================================

ADDITIONAL_BANK_CODES = [
    ("IDIB", "INDIAN BANK"), ("PSIB", "PUNJAB & SIND BANK"), ("IOBA", "INDIAN OVERSEAS BANK"),
    ("BARB", "BANK OF BARODA"), ("MAHB", "BANK OF MAHARASHTRA"), ("BKID", "BANK OF INDIA"),
    ("CBIN", "CENTRAL BANK OF INDIA"), ("DBSS", "DBS BANK INDIA LIMITED"), ("HSBC", "HSBC BANK OMAN S.A.O.G / INDIA"),
    ("SCBL", "STANDARD CHARTERED BANK"), ("CITI", "CITIBANK N.A."), ("DEUT", "DEUTSCHE BANK AG"),
    ("YESB", "YES BANK LIMITED"), ("IDFB", "IDFC FIRST BANK LIMITED"), ("FED", "FEDERAL BANK LIMITED"),
    ("INDB", "INDUSIND BANK LIMITED"), ("SIBL", "SOUTH INDIAN BANK LIMITED"), ("KARB", "KARNATAKA BANK LIMITED"),
    ("KVBL", "KARUR VYSYA BANK LIMITED"), ("CSBK", "CSB BANK LIMITED"), ("DCBL", "DCB BANK LIMITED"),
    ("JAKA", "JAMMU AND KASHMIR BANK LIMITED"), ("BAND", "BANDHAN BANK LIMITED"), ("ESAF", "ESAF SMALL FINANCE BANK LIMITED"),
    ("EQUA", "EQUITAS SMALL FINANCE BANK LIMITED"), ("UJVN", "UJJIVAN SMALL FINANCE BANK LIMITED"), ("FINO", "FINO PAYMENTS BANK LIMITED"),
    ("PAYTM", "PAYTM PAYMENTS BANK LIMITED"), ("IPPB", "INDIA POST PAYMENTS BANK"), ("AIRP", "AIRTEL PAYMENTS BANK LIMITED"),
    ("JIOB", "JIO PAYMENTS BANK LIMITED"), ("BDBL", "BANDHAN BANK"), ("NSPB", "NSDL PAYMENTS BANK LIMITED"),
    ("SGBK", "SURAYODAY SMALL FINANCE BANK"), ("UTKS", "UTKARSH SMALL FINANCE BANK"), ("JSFB", "JANA SMALL FINANCE BANK"),
    ("CLBL", "CAPITAL SMALL FINANCE BANK"), ("UNITY", "UNITY SMALL FINANCE BANK"), ("SHGB", "SHIVALIK SMALL FINANCE BANK"),
    ("NESF", "NORTH EAST SMALL FINANCE BANK")
]

EDGE_CASE_DESCRIPTIONS = [
    # Special characters & quotes
    'FT - "SELECTIVE TRADING" - 5020009988 - \t SPECIAL CHARS & QUOTES',
    "NEFT/000981273/ICIC/'O''CONNOR & SONS' INC",
    "IMPS/P2A/881273/UTIB/9180/SELECTRICITY--TWO--PRIVATE--LIMITED // RECON RESULT",
    "UPI-PAYMENT-M&M\\SERVICES-XXXXXX1029-SBIN0001928-109283712-260101000000",
    "CHARGES: LATE FEE & INTEREST @ 18% (INC. GST @ 18.00%)",
    "REFUND: ITEM #1029/B & C - MULTI-ITEM CANCELLED",
    "TRANSFER TO AC# 9010-0987-6543-21 | BATCH #991823",
    # SQL injection attempt / raw strings test
    "NEFT - '; DROP TABLE transaction; -- - 95604250",
    "IMPS/P2A/10293' OR '1'='1/UTIB/9180",
    # Multi-word & Whitespace
    "  NEFT   WITH   LEADING   AND   TRAILING   SPACES   ",
    "FT-RERELI2010000810-\nRELIANCEDIGITAL RETAIL LTD\n   SELECT CITY SAKET DELHI",
    # Unicode / non-ASCII
    "UPI-SHREE RAM STORE-₹500-SBIN0001029-SUCCESS",
    "IMPS/P2A/99182371/HDFC/₹10000 CASHBACK PROMO",
    # Typical high volume formats
    "FT -  95842568 -  50200013729069 - SELECTION ELECTRONICS DAHISAR EAST",
    "UPI-NAVYUG SELECTION-XXXXXX8672-AUBL0002125-103293775381-260514201735136",
    "NEFT  - UTIB0002678 - 95604250 - 915020031685136 - UMANG SELECTIONHAPURBPES DPF10129",
    "NEFT/000483399203/ICIC/PARESH VIKRANT GHASE",
    "IMPS/P2A/600228462725/UTIB/918020101986700/00/INET/9211/SELECTIONMALIGAI",
    "IMPS OW/507614422198/Gautam singh/SBIN/43292707719",
    "CARD SWIPE POS-MERCHANT #991823 DAHISAR",
    "ACH CREDIT - SALARY DISBURSEMENT - BATCH 8829"
]

ENCRYPTED_UTRS = [
    "jhI5nAdyb1qOEjmcB3JvWjC6tTO+ZPVqBFPm/GiErC4TRBWRQ5ylPG3p",
    "jhI5nAdyb1qOEjmcB3JvWjC9tzSzbvtkBlK+NSqsiL164ZK8Bl8cYg8y1l8=",
    "jhI5nAdyb1qOEjmcB3JvWknJwkXCbf1jBFm1NhmQqR0EoF/PNGRDCa1+UTH2I/tV",
    "jhI5nAdyb1qOEjmcB3JvWknJwkXCbf1jBFm1NhSSrh+QRpxgqe0VEdKaiI24S8Up",
    "jhI5nAdyb1qOEjmcB3JvWknJwkXCbf1jBFm1MBKUrRvYyGUaTtHlT1wi23x31CRl",
    "jhI5nAdyb1qOEjmcB3JvWjC7sDW9ZPtrAllbY+gS/wWLLijTRu8nX6op",
    "aB89xZq1LmNpOqRsTuVwXyZ3aBcDeFgHiJkLmNoPqRsTuVwXyZ3aBcDeFgHiJkLm",
    "zY76wVu4TsRqPoNmLkJiHgFeDcBa3Z2YxWvUtSrQpOnMlKjIhGfEdCbA1z0YxWvU"
]

REPEATED_REF_IDS = ["S31125841", "HDFCH01078329532", "103293775381", "REF_DUPLICATE_9999", "REF_SHARED_1000"]

def generate_aes256_encrypted_utrs(count=8):
    """Generate realistic UTR numbers and encrypt them with AES256."""
    plaintext_utrs = [
        "HDFC20250101000001",
        "ICIC20250102000002",
        "SBIN20250103000003",
        "UTIB20250104000004",
        "KKBK20250105000005",
        "CNRB20250106000006",
        "UBIN20250107000007",
        "AUBL20250108000008",
    ]
    
    encrypted_utrs = []
    for utr in plaintext_utrs[:count]:
        try:
            encrypted = AccountEncryption.encrypt_utr_aes256(utr)
            encrypted_utrs.append(encrypted)
        except Exception as e:
            print(f"Warning: Failed to encrypt UTR {utr}: {e}")
            # Fallback to plaintext if encryption fails
            encrypted_utrs.append(utr)
    
    return encrypted_utrs

# Generate encrypted UTRs with AES256
ENCRYPTED_UTRS = []
try:
    ENCRYPTED_UTRS = generate_aes256_encrypted_utrs(8)
except Exception as e:
    print(f"Warning: Could not generate AES256-encrypted UTRs: {e}")
    print("Falling back to sample encrypted values...")
    # Fallback sample values if encryption module is not available
    ENCRYPTED_UTRS = [
        "AES256:gAAAAABlq1Z1...",  # Placeholder
        "AES256:gAAAAABlq1Z2...",
        "AES256:gAAAAABlq1Z3...",
        "AES256:gAAAAABlq1Z4...",
        "AES256:gAAAAABlq1Z5...",
        "AES256:gAAAAABlq1Z6...",
        "AES256:gAAAAABlq1Z7...",
        "AES256:gAAAAABlq1Z8...",
    ]

REPEATED_UTRS = [
    ENCRYPTED_UTRS[0] if ENCRYPTED_UTRS else "UTR_SHARED_99999",
    "UTR_SHARED_PLAINTEXT"
]

def generate_large_dataset(num_transactions=500000, num_accounts=10000):
    print(f"[*] Generating Large Dataset ({num_transactions:,} txns, {num_accounts:,} accounts, ~50 banks)...")
    
    # 1. Banks
    banks = list(SMALL_BANKS)
    for code, name in ADDITIONAL_BANK_CODES:
        banks.append({"bank_code": code, "bank_name": name})
        
    bank_codes = [b["bank_code"] for b in banks]
    
    with open(LARGE_DIR / "bank.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bank_code", "bank_name"])
        for b in banks:
            w.writerow([b["bank_code"], b["bank_name"]])
            
    print(f"    [+] {len(banks)} Banks written to data/large/bank.csv")
    
    # 2. Accounts
    accounts = list(SMALL_ACCOUNTS)
    account_ids = [a["account_id"] for a in SMALL_ACCOUNTS]
    
    # Program IDs include standard (4, 21, 46) and edge case 0
    program_ids = [4, 21, 46, 0, 99]
    
    # Pre-generate remaining accounts up to num_accounts
    print("    [*] Pre-generating accounts...")
    accounts_to_generate = num_accounts - len(SMALL_ACCOUNTS)
    
    with open(LARGE_DIR / "account.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["account_id", "entity_id", "account_number", "program_id", "available_balance", "bank_code"])
        
        # Write small accounts first
        for a in SMALL_ACCOUNTS:
            w.writerow([a["account_id"], a["entity_id"], a["account_number"], a["program_id"], f"{a['available_balance']:.2f}", a["bank_code"]])
            
        for i in range(accounts_to_generate):
            acc_id = str(uuid.uuid4())
            ent_id = str(uuid.uuid4())
            
            # Edge cases for account numbers & balances
            rand_val = random.random()
            if rand_val < 0.05:
                # Extreme negative balance
                balance = round(random.uniform(-500000000.00, -100000.00), 2)
            elif rand_val < 0.10:
                # Zero balance
                balance = 0.00
            elif rand_val < 0.15:
                # Extreme high positive balance
                balance = round(random.uniform(500000000.00, 999999999.99), 2)
            else:
                # Standard balance
                balance = round(random.uniform(-50000000.00, 100000000.00), 2)
                
            acc_num = f"{random.randint(10,90)}{random.randint(1000000000,9999999999)}"
            prog_id = random.choice(program_ids)
            b_code = random.choice(bank_codes)
            
            w.writerow([acc_id, ent_id, acc_num, prog_id, f"{balance:.2f}", b_code])
            account_ids.append(acc_id)
            
    print(f"    [+] {num_accounts:,} Accounts written to data/large/account.csv")
    
    # 3. Transactions
    print(f"    [*] Generating {num_transactions:,} transactions (streaming to CSV)...")
    
    start_date = datetime(2023, 1, 1, 0, 0, 0)
    end_date = datetime(2026, 8, 31, 23, 59, 59)
    total_seconds = int((end_date - start_date).total_seconds())
    
    with open(LARGE_DIR / "transaction.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["transaction_id", "account_id", "transaction_date", "transaction_type", "description", "transaction_amount", "transaction_reference_id", "utr_number"])
        
        # 1. Write small transactions first
        for t in SMALL_TRANSACTIONS:
            w.writerow([
                t["transaction_id"], t["account_id"], t["transaction_date"], t["transaction_type"],
                t["description"], f"{t['transaction_amount']:.2f}", t["transaction_reference_id"], t["utr_number"]
            ])
            
        written = len(SMALL_TRANSACTIONS)
        
        while written < num_transactions:
            txn_id = str(uuid.uuid4())
            acc_id = random.choice(account_ids)
            
            # Timestamp generation (with edge cases: leap day 2024-02-29, microsecond precision, boundary timestamps)
            rand_time = random.random()
            if rand_time < 0.01:
                # Leap day 2024-02-29
                dt = datetime(2024, 2, 29, random.randint(0,23), random.randint(0,59), random.randint(0,59), random.randint(0, 999999))
            elif rand_time < 0.02:
                # Year-end boundary
                dt = datetime(2025, 12, 31, 23, 59, 59, 999999)
            elif rand_time < 0.03:
                # New year boundary
                dt = datetime(2026, 1, 1, 0, 0, 0, 0)
            else:
                sec_offset = random.randint(0, total_seconds)
                microsec = random.randint(0, 999999)
                dt = start_date + timedelta(seconds=sec_offset, microseconds=microsec)
                
            date_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")
            txn_type = "debit" if random.random() < 0.65 else "credit"
            
            # Amount edge cases
            rand_amt = random.random()
            if rand_amt < 0.02:
                # Zero amount transaction
                amt = 0.00
            elif rand_amt < 0.05:
                # Micro amount (0.01)
                amt = 0.01
            elif rand_amt < 0.08:
                # Extreme high transaction amount
                amt = round(random.uniform(50000000.00, 999999999.99), 2)
            else:
                # Standard amounts
                amt = round(random.uniform(10.00, 500000.00), 2)
                
            # Description edge cases
            if random.random() < 0.15:
                desc = random.choice(EDGE_CASE_DESCRIPTIONS)
            else:
                prefix = random.choice(["NEFT", "UPI", "IMPS", "FT", "RTGS", "ACH", "POS"])
                desc = f"{prefix} - {random.choice(bank_codes)} - TXN #{random.randint(10000,999999)} - PAYMENT"
                
            # Reference ID edge cases (Null/Empty, Duplicates, Standard)
            rand_ref = random.random()
            if rand_ref < 0.20:
                # Null / Empty reference ID
                ref_id = ""
            elif rand_ref < 0.25:
                # Duplicate / Shared reference ID
                ref_id = random.choice(REPEATED_REF_IDS)
            else:
                ref_id = f"REF{random.randint(100000000, 999999999)}"
                
            # UTR edge cases (Null/Empty, Encrypted Base64, Shared, Plaintext)
            rand_utr = random.random()
            if rand_utr < 0.35:
                # Null / Empty UTR
                utr = ""
            elif rand_utr < 0.60:
                # Encrypted Base64 string UTR
                utr = random.choice(ENCRYPTED_UTRS)
            elif rand_utr < 0.65:
                # Duplicate UTR
                utr = random.choice(REPEATED_UTRS)
            else:
                # Plaintext UTR
                utr = f"UTR{random.choice(bank_codes)}{dt.strftime('%Y%m%d')}{random.randint(100000,999999)}"
                
            w.writerow([txn_id, acc_id, date_str, txn_type, desc, f"{amt:.2f}", ref_id, utr])
            
            written += 1
            if written % 100000 == 0:
                print(f"    ... {written:,} / {num_transactions:,} transactions generated")
                
    print(f"[+] Large dataset generation complete: {LARGE_DIR / 'transaction.csv'}")

if __name__ == "__main__":
    write_small_dataset()
    generate_large_dataset(num_transactions=500000, num_accounts=10000)
