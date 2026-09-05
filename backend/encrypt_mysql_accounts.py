"""
One-off script: encrypt plaintext account_number values already stored in the live
MySQL database, in place, using the ENCRYPTION_KEY from .env. Populates
account_number_masked with a display-safe masked value at the same time.

Usage (from repo root or backend/):
    python encrypt_mysql_accounts.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import pymysql  # noqa: E402  (import after load_dotenv so ENCRYPTION_KEY is available)
from encryption import AccountEncryption  # noqa: E402


def looks_encrypted(value: str) -> bool:
    """Fernet tokens always start with this prefix; used to avoid double-encrypting."""
    return value.startswith("gAAAAA")


def main():
    config = {
        "host": os.getenv("MYSQL_HOST"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": os.getenv("MYSQL_DATABASE"),
    }
    if not (config["host"] and config["user"] and config["database"]):
        print("MYSQL_HOST/MYSQL_USER/MYSQL_DATABASE must be set in .env")
        sys.exit(1)

    conn = pymysql.connect(**config)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT account_id, account_number FROM account")
            rows = cur.fetchall()

            updated = 0
            for account_id, account_number in rows:
                if looks_encrypted(account_number):
                    continue  # already encrypted, skip

                encrypted = AccountEncryption.encrypt_account_number(account_number)
                masked = AccountEncryption.mask_account_number(account_number)
                cur.execute(
                    "UPDATE account SET account_number = %s, account_number_masked = %s WHERE account_id = %s",
                    (encrypted, masked, account_id),
                )
                updated += 1

        conn.commit()
        print(f"Encrypted {updated} account number(s) out of {len(rows)} total rows in MySQL.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
