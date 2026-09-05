"""
One-time dev utility: replace the sample datasets' sensitive columns with real AES-256-GCM
ciphertext (see backend/crypto_utils.py), so the decrypt-at-runtime path has something genuine
to decrypt instead of the synthetic random-looking placeholder strings the generator produced.

- account.account_number: currently plaintext -> encrypted in place.
- transaction.utr_number: currently fake ciphertext-looking strings with no real underlying
  plaintext -> replaced with a synthetic plaintext UTR (derived from transaction_id, so it's
  reproducible) encrypted for real. Empty cells stay empty (utr_number is legitimately absent
  for some transactions per the schema doc).
- transaction.transaction_reference_id is explicitly NOT sensitive (plaintext, directly
  searchable per the schema doc) and is left untouched.

Not part of the request-serving runtime - run manually, once, whenever the sample data is
regenerated: `python scripts/encrypt_sensitive_data.py`. Requires ENCRYPTION_KEY in the
environment (see .env).
"""

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

import crypto_utils

ACCOUNT_FILES = [
    REPO_ROOT / "data" / "account.csv",
    REPO_ROOT / "data" / "small" / "account.csv",
    REPO_ROOT / "data" / "large" / "account.csv",
]
TRANSACTION_FILES = [
    REPO_ROOT / "data" / "transaction.csv",
    REPO_ROOT / "data" / "small" / "transaction.csv",
    REPO_ROOT / "data" / "large" / "transaction.csv",
]


def encrypt_account_file(path: Path):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if row.get("account_number"):
            row["account_number"] = crypto_utils.encrypt_value(row["account_number"])
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  encrypted account_number in {len(rows)} rows -> {path}")


def encrypt_transaction_file(path: Path):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    encrypted_count = 0
    for row in rows:
        if row.get("utr_number"):
            synthetic_plaintext = f"UTR{row['transaction_id'].replace('-', '').upper()[:16]}"
            row["utr_number"] = crypto_utils.encrypt_value(synthetic_plaintext)
            encrypted_count += 1
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  encrypted utr_number in {encrypted_count}/{len(rows)} rows -> {path}")


if __name__ == "__main__":
    if not crypto_utils._get_aesgcm():
        print("ERROR: ENCRYPTION_KEY not set (check .env). Aborting.")
        sys.exit(1)

    print("Encrypting account_number:")
    for f in ACCOUNT_FILES:
        encrypt_account_file(f)

    print("Encrypting utr_number:")
    for f in TRANSACTION_FILES:
        encrypt_transaction_file(f)

    print("Done.")
