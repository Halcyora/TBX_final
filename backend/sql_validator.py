"""
SQL Query Validation
Static checks before LLM execution, and LLM-based semantic validation
"""

import re
import logging
from typing import Tuple, List, Dict, Any
import sqlparse
from sqlparse.sql import IdentifierList, Identifier, Where, Parenthesis
from database import get_db

logger = logging.getLogger(__name__)

class SQLValidator:
    """Validates SQL queries for safety and correctness"""
    
    # Allowed tables in the TBX financial database
    ALLOWED_TABLES = {
        'bank',       # bank_code, bank_name
        'account',    # account_id, entity_id, account_number, program_id, available_balance, bank_code
        'transaction' # transaction_id, account_id, transaction_date, transaction_type, description, transaction_amount, transaction_reference_id, utr_number
    }
    
    # Dangerous SQL keywords to prevent
    DANGEROUS_KEYWORDS = {
        'DROP', 'DELETE', 'UPDATE', 'INSERT', 'CREATE', 'ALTER', 
        'TRUNCATE', 'EXEC', 'EXECUTE'
    }
    
    @staticmethod
    def validate_query(sql: str) -> Tuple[bool, str]:
        """
        Validate SQL query with multiple checks
        Returns: (is_valid, error_message)
        """
        # Remove whitespace and normalize
        sql = sql.strip()
        
        # 1. Check syntax
        valid_syntax, syntax_error = SQLValidator._check_syntax(sql)
        if not valid_syntax:
            return False, f"Syntax error: {syntax_error}"
        
        # 2. Check for dangerous operations
        safe_ops, danger_msg = SQLValidator._check_dangerous_operations(sql)
        if not safe_ops:
            return False, f"Security check failed: {danger_msg}"
        
        # 3. Check table references
        valid_tables, table_msg = SQLValidator._check_table_references(sql)
        if not valid_tables:
            return False, f"Table validation failed: {table_msg}"
        
        # 4. Check column references (basic)
        valid_cols, col_msg = SQLValidator._check_basic_columns(sql)
        if not valid_cols:
            return False, f"Column validation warning: {col_msg}"
        
        # 5. Database EXPLAIN dry-run check (verifies real column names and schema)
        try:
            db = get_db()
            db.conn.execute(f"EXPLAIN {sql}")
        except Exception as e:
            return False, f"Schema validation failed: {str(e)}"
        
        logger.info("SQL query passed all validation checks")
        return True, "Query is valid"
    
    @staticmethod
    def _check_syntax(sql: str) -> Tuple[bool, str]:
        """Check basic SQL syntax"""
        try:
            parsed = sqlparse.parse(sql)
            if not parsed:
                return False, "Empty query"
            
            # Check if it's a SELECT statement
            first_token = parsed[0].token_first(skip_ws=True, skip_cm=True)
            if first_token.ttype is None or 'SELECT' not in str(first_token).upper():
                return False, "Query must be a SELECT statement"
            
            return True, ""
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def _check_dangerous_operations(sql: str) -> Tuple[bool, str]:
        """Prevent DROP, DELETE, UPDATE, etc."""
        sql_upper = sql.upper()
        
        for keyword in SQLValidator.DANGEROUS_KEYWORDS:
            if re.search(r'\b' + keyword + r'\b', sql_upper):
                return False, f"'{keyword}' operations not allowed"
        
        return True, ""
    
    @staticmethod
    def _check_table_references(sql: str) -> Tuple[bool, str]:
        """Verify only allowed tables are referenced (regex-based - robust against
        sqlparse token-type quirks that previously let unknown table names slip through)"""
        try:
            matches = re.findall(r'\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)', sql, re.IGNORECASE)
            tables_found = {m.lower() for m in matches}

            invalid_tables = tables_found - SQLValidator.ALLOWED_TABLES
            if invalid_tables:
                return False, f"Unauthorized table access: {invalid_tables}"
            
            return True, ""
        except Exception as e:
            logger.warning(f"Table reference check warning: {e}")
            return True, ""  # Don't fail on parsing errors
    
    @staticmethod
    def _check_basic_columns(sql: str) -> Tuple[bool, str]:
        """Basic column reference check (not comprehensive)"""
        try:
            # Look for obviously wrong patterns
            if 'SELECT *' in sql.upper():
                # SELECT * is okay for this use case
                pass
            
            if re.search(r'LIMIT\s+\d+', sql, re.IGNORECASE):
                limit = re.search(r'LIMIT\s+(\d+)', sql, re.IGNORECASE).group(1)
                if int(limit) > 100000:
                    return False, "LIMIT exceeds maximum allowed (100000)"
            
            return True, ""
        except Exception as e:
            logger.warning(f"Column check warning: {e}")
            return True, ""
    
    @staticmethod
    def get_table_schema() -> Dict[str, List[Dict[str, Any]]]:
        """Get schema information for all allowed tables"""
        schema = {}
        db = get_db()
        
        for table in SQLValidator.ALLOWED_TABLES:
            try:
                # Get column info from DuckDB
                cols = db.conn.execute(f"DESCRIBE {table}").fetchall()
                schema[table] = [
                    {"name": col[0], "type": str(col[1]), "nullable": col[2]}
                    for col in cols
                ]
            except Exception as e:
                logger.warning(f"Failed to get schema for {table}: {e}")
                schema[table] = []
        
        return schema
    
    @staticmethod
    def format_schema_for_prompt() -> str:
        """Format schema info for LLM prompts"""
        schema = SQLValidator.get_table_schema()
        
        formatted = "DATABASE SCHEMA:\n"
        for table, columns in schema.items():
            col_str = ", ".join([f"{col['name']} ({col['type']})" for col in columns])
            formatted += f"- {table}: {col_str}\n"
        
        return formatted


class QueryResultValidator:
    """Validates query results for anomalies and quality"""
    
    @staticmethod
    def check_result_integrity(results: List[Dict[str, Any]], 
                              expected_columns: List[str]) -> Tuple[bool, str]:
        """Check if results have expected structure"""
        if not results:
            return True, "Empty result set"
        
        # Check columns
        first_row = results[0]
        actual_columns = set(first_row.keys())
        expected = set(expected_columns) if expected_columns else actual_columns
        
        if not expected.issubset(actual_columns):
            missing = expected - actual_columns
            return False, f"Missing expected columns: {missing}"
        
        return True, ""
    
    @staticmethod
    def detect_data_quality_issues(results: List[Dict[str, Any]]) -> List[str]:
        """Check for common data quality issues"""
        issues = []
        
        if not results:
            return ["No results returned"]
        
        # Check for null/missing values
        null_count = 0
        for row in results:
            for value in row.values():
                if value is None or (isinstance(value, str) and value.strip() == ''):
                    null_count += 1
        
        null_pct = (null_count / (len(results) * len(results[0]))) * 100
        if null_pct > 30:
            issues.append(f"High percentage of null values: {null_pct:.1f}%")
        
        # Check for unusual value ranges (e.g., negative amounts)
        for row in results:
            for key, value in row.items():
                if isinstance(value, (int, float)) and value < 0:
                    if 'amount' in key.lower():
                        issues.append(f"Negative amount found: {key}={value}")
        
        return issues
