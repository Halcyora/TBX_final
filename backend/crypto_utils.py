"""
Decryption of sensitive columns (account.account_number, transaction.utr_number) at read time.

Scheme: AES-256-GCM (authenticated encryption, 256-bit key). Note SHA-256 itself is a one-way
hash - it cannot decrypt anything - so "SHA-256" isn't a decryption scheme on its own; AES-256 is
the actual reversible cipher used here. Each encrypted value is `base64(nonce[12 bytes] ||
ciphertext+tag)`, one self-contained string per cell, same shape as any other VARCHAR value.

Design (see INTERNAL_NOTES.md for the full writeup):
- One server-held 256-bit key, loaded once from the ENCRYPTION_KEY env var (base64). No
  per-request/per-user key handling - the problem statement explicitly puts multi-tenant/
  production-grade auth out of scope, so a single shared key matches the actual scope here.
- Decrypt ONLY the rows a query is about to return, AFTER execution - never eagerly at load time
  or as part of filtering. AES-GCM ciphertext is non-deterministic (a random nonce per value), so
  the same plaintext never encrypts to the same ciphertext twice - a plain WHERE/JOIN can't match
  it anyway. See sql_validator.py's _check_encrypted_column_usage for the static guard that keeps
  the LLM from generating a filter/join on these columns in the first place.
- utr_number can legitimately be plaintext or NULL for some rows (per the schema doc) - decrypt
  is a graceful no-op (returns the original value) for anything that isn't valid ciphertext for
  our key, never a crash.
"""

import os
import base64
import logging
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

SENSITIVE_COLUMNS = ("account_number", "utr_number")
NONCE_SIZE = 12  # bytes, the standard/recommended size for AES-GCM

_aesgcm: Optional[AESGCM] = None
_key_load_attempted = False


def _get_aesgcm() -> Optional[AESGCM]:
    """Lazy singleton. Returns None (not an exception) if ENCRYPTION_KEY isn't configured, so a
    dev environment without it set still runs - sensitive columns just pass through undecrypted."""
    global _aesgcm, _key_load_attempted
    if _key_load_attempted:
        return _aesgcm
    _key_load_attempted = True
    key_b64 = os.getenv("ENCRYPTION_KEY")
    if not key_b64:
        logger.warning("ENCRYPTION_KEY not set - sensitive columns will be returned undecrypted")
        return None
    try:
        key = base64.urlsafe_b64decode(key_b64)
        if len(key) != 32:
            raise ValueError(f"ENCRYPTION_KEY must decode to 32 bytes for AES-256, got {len(key)}")
        _aesgcm = AESGCM(key)
    except Exception as e:
        logger.error(f"Invalid ENCRYPTION_KEY, decryption disabled: {e}")
        _aesgcm = None
    return _aesgcm


def decrypt_value(value: Any) -> Any:
    """Decrypt a single value if it's valid AES-256-GCM ciphertext for our key; otherwise return
    it unchanged (covers legitimately-plaintext UTRs, NULLs, and a missing/invalid key)."""
    if not isinstance(value, str) or not value:
        return value
    aesgcm = _get_aesgcm()
    if aesgcm is None:
        return value
    try:
        raw = base64.urlsafe_b64decode(value.encode())
        if len(raw) <= NONCE_SIZE:
            return value
        nonce, ciphertext = raw[:NONCE_SIZE], raw[NONCE_SIZE:]
        return aesgcm.decrypt(nonce, ciphertext, None).decode()
    except Exception:
        return value  # not actually our ciphertext (or wrong key) - pass through, don't crash


def decrypt_row(row: Dict[str, Any], columns: tuple = SENSITIVE_COLUMNS) -> Dict[str, Any]:
    """Decrypt the sensitive columns present in one result row - matched by substring, not exact
    name, so an alias like `MAX(account_number) AS max_account_number` still gets decrypted
    (found necessary while testing: the model commonly renames a column it aggregates/joins
    around). A query that never selected the column at all is untouched either way."""
    for key in row:
        if any(col in key.lower() for col in columns):
            row[key] = decrypt_value(row[key])
    return row


def decrypt_results(rows: List[Dict[str, Any]], columns: tuple = SENSITIVE_COLUMNS) -> List[Dict[str, Any]]:
    """Decrypt sensitive columns across a result set - the only place this should ever be
    called from is after a query has already executed and returned its (small, LIMIT-capped)
    result set, never before/during filtering."""
    return [decrypt_row(row, columns) for row in rows]


def encrypt_value(value: str) -> str:
    """Encrypt a plaintext value. Used by scripts/encrypt_sensitive_data.py to prepare
    realistic ciphertext test data - not part of the request-serving runtime path."""
    aesgcm = _get_aesgcm()
    if aesgcm is None:
        raise RuntimeError("ENCRYPTION_KEY not set - cannot encrypt")
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = aesgcm.encrypt(nonce, value.encode(), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()
