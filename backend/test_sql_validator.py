"""
Self-check for SQLValidator's join-cost guard (an OR'd join condition - the pattern that took
938s/~15GB on 500K rows during benchmarking - must be rejected before ever touching the database)
and its encrypted-column guard (a WHERE/JOIN match against account_number/utr_number can never
succeed, since each row's ciphertext was encrypted independently).
Run directly: python test_sql_validator.py
"""
from sql_validator import SQLValidator


def test_or_join_condition_rejected():
    sql = """SELECT t1.transaction_reference_id, COUNT(DISTINCT t2.account_id) as c
FROM transaction t1
JOIN transaction t2 ON t1.transaction_reference_id = t2.transaction_reference_id OR t1.utr_number = t2.utr_number
GROUP BY t1.transaction_reference_id
HAVING c > 1"""
    is_valid, msg = SQLValidator.validate_query(sql)
    assert is_valid is False
    assert "OR" in msg


def test_normal_equi_join_accepted():
    sql = "SELECT a.account_id, b.bank_name FROM account a JOIN bank b ON a.bank_code = b.bank_code"
    is_valid, msg = SQLValidator.validate_query(sql)
    assert is_valid is True, msg


def test_or_in_where_clause_is_fine():
    """OR is only dangerous in a JOIN's ON clause, not in an ordinary WHERE filter."""
    sql = "SELECT * FROM transaction WHERE transaction_type = 'credit' OR transaction_type = 'debit'"
    is_valid, msg = SQLValidator.validate_query(sql)
    assert is_valid is True, msg


def test_encrypted_column_equality_filter_rejected():
    sql = "SELECT * FROM account WHERE account_number = '50200013729069'"
    is_valid, msg = SQLValidator.validate_query(sql)
    assert is_valid is False
    assert "encrypted" in msg.lower()


def test_encrypted_column_join_rejected():
    sql = ("SELECT * FROM transaction t1 JOIN transaction t2 "
           "ON t1.utr_number = t2.utr_number AND t1.transaction_id != t2.transaction_id")
    is_valid, msg = SQLValidator.validate_query(sql)
    assert is_valid is False
    assert "encrypted" in msg.lower()


def test_encrypted_column_is_null_check_allowed():
    sql = "SELECT * FROM transaction WHERE utr_number IS NOT NULL"
    is_valid, msg = SQLValidator.validate_query(sql)
    assert is_valid is True, msg


def test_encrypted_column_select_and_group_by_allowed():
    sql = ("SELECT account_id, account_number, COUNT(*) as c FROM account "
           "GROUP BY account_id, account_number")
    is_valid, msg = SQLValidator.validate_query(sql)
    assert is_valid is True, msg


if __name__ == "__main__":
    test_or_join_condition_rejected()
    test_normal_equi_join_accepted()
    test_or_in_where_clause_is_fine()
    test_encrypted_column_equality_filter_rejected()
    test_encrypted_column_join_rejected()
    test_encrypted_column_is_null_check_allowed()
    test_encrypted_column_select_and_group_by_allowed()
    print("All sql_validator self-checks passed.")
