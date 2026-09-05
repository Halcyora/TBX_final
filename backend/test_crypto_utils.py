"""
Self-check for crypto_utils.py: round-trip encrypt/decrypt, and graceful pass-through for
plaintext/empty/None/wrong-key values (never raise - a missing UTR or a legitimately-plaintext
one must not break the pipeline).
Run directly: python test_crypto_utils.py
"""
import os
import base64

os.environ["ENCRYPTION_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode()

import crypto_utils


def test_round_trip():
    ciphertext = crypto_utils.encrypt_value("50200013729069")
    assert ciphertext != "50200013729069"
    assert crypto_utils.decrypt_value(ciphertext) == "50200013729069"


def test_two_encryptions_of_same_value_differ():
    """Non-deterministic (random nonce per call) - this is exactly why SQL can't filter on it."""
    a = crypto_utils.encrypt_value("50200013729069")
    b = crypto_utils.encrypt_value("50200013729069")
    assert a != b
    assert crypto_utils.decrypt_value(a) == crypto_utils.decrypt_value(b) == "50200013729069"


def test_passthrough_for_non_ciphertext():
    assert crypto_utils.decrypt_value("plain-utr-123") == "plain-utr-123"
    assert crypto_utils.decrypt_value("") == ""
    assert crypto_utils.decrypt_value(None) is None


def test_decrypt_row_only_touches_present_sensitive_columns():
    ciphertext = crypto_utils.encrypt_value("50200013729069")
    row = {"account_id": "abc", "account_number": ciphertext, "program_id": 21}
    out = crypto_utils.decrypt_row(dict(row))
    assert out["account_number"] == "50200013729069"
    assert out["account_id"] == "abc" and out["program_id"] == 21

    row_without_it = {"transaction_id": "t1", "transaction_amount": 100}
    assert crypto_utils.decrypt_row(dict(row_without_it)) == row_without_it


def test_decrypt_row_matches_aliased_column_names():
    """A query that aliases the column (e.g. MAX(account_number) AS max_account_number) must
    still get decrypted - found necessary while testing complex queries."""
    ciphertext = crypto_utils.encrypt_value("50200013729069")
    row = {"bank_code": "HDFC", "max_account_number": ciphertext}
    out = crypto_utils.decrypt_row(dict(row))
    assert out["max_account_number"] == "50200013729069"


if __name__ == "__main__":
    test_round_trip()
    test_two_encryptions_of_same_value_differ()
    test_passthrough_for_non_ciphertext()
    test_decrypt_row_only_touches_present_sensitive_columns()
    test_decrypt_row_matches_aliased_column_names()
    print("All crypto_utils self-checks passed.")
