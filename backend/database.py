"""
DuckDB Database Management
Handles financial data loading and query execution
Schema: bank, account, transaction (TBX Finance Assistant)
"""

import os
import duckdb
import threading
from pathlib import Path
from typing import Any, List, Dict
import logging

logger = logging.getLogger(__name__)

# Resolved relative to this file, not the process's cwd, so `python main.py` behaves the same
# whether launched from the repo root or from backend/ (the data/ directory lives at repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = str(REPO_ROOT / "data" / "finance.db")


class FinanceDB:
    """DuckDB wrapper for TBX financial data queries"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH, dataset: str = "small"):
        """
        Initialize database connection
        Args:
            db_path: Path to DuckDB database file
            dataset: 'small' (10 records) or 'large' (500k+ records)
        """
        self.db_path = db_path
        self.dataset = dataset
        self.conn = None
        self.query_timeout_seconds = float(os.getenv("QUERY_TIMEOUT_SECONDS", "15"))
        self.initialize()
    
    def initialize(self):
        """Initialize DuckDB connection and load data"""
        try:
            self.conn = duckdb.connect(self.db_path, read_only=False)
            logger.info(f"Connected to DuckDB: {self.db_path}")
            self._load_data_from_csv()
            logger.info("Data loaded successfully")
        except Exception as e:
            logger.error(f"Failed to initialize DuckDB: {e}")
            raise
    
    def _load_data_from_csv(self):
        """Load CSV files into DuckDB tables from selected dataset"""
        # Determine dataset directory
        if self.dataset == "large":
            data_dir = REPO_ROOT / "data" / "large"
        else:  # default to small
            data_dir = REPO_ROOT / "data"
        
        # TBX Schema: bank, account, transaction
        # Real column types (matching the DDL in "TBX - Database Schema.md") instead of
        # ALL_VARCHAR - lets the LLM write plain comparisons/SUM/AVG without remembering to
        # CAST every numeric or date column, removing a whole class of small-model mistakes.
        tables = {
            "bank": ("bank.csv", {
                "bank_code": "VARCHAR", "bank_name": "VARCHAR",
            }),
            "account": ("account.csv", {
                "account_id": "VARCHAR", "entity_id": "VARCHAR", "account_number": "VARCHAR",
                "program_id": "INTEGER", "available_balance": "DECIMAL(18,2)", "bank_code": "VARCHAR",
            }),
            "transaction": ("transaction.csv", {
                "transaction_id": "VARCHAR", "account_id": "VARCHAR", "transaction_date": "TIMESTAMP",
                "transaction_type": "VARCHAR", "description": "VARCHAR", "transaction_amount": "DECIMAL(18,2)",
                "transaction_reference_id": "VARCHAR", "utr_number": "VARCHAR",
            }),
        }

        logger.info(f"Loading {self.dataset} dataset from {data_dir}")

        for table_name, (csv_file, columns) in tables.items():
            csv_path = data_dir / csv_file
            if csv_path.exists():
                try:
                    # Read CSV into table
                    self.conn.execute(f"""
                        CREATE OR REPLACE TABLE {table_name} AS
                        SELECT * FROM read_csv('{csv_path}', columns={columns})
                    """)
                    
                    # Get row count
                    row_count = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                    logger.info(f"  ✓ Loaded {table_name}: {row_count:,} rows")
                    
                except Exception as e:
                    logger.error(f"Failed to load {table_name}: {e}")
                    raise
            else:
                logger.error(f"CSV file not found: {csv_path}")
                raise FileNotFoundError(f"Dataset file not found: {csv_path}")
        
        # Create useful indexes for faster queries
        self._create_indexes()
    
    def _create_indexes(self):
        """Create indexes on commonly queried columns"""
        try:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_code ON bank(bank_code)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_account_id ON account(account_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_account_bank ON account(bank_code)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_txn_id ON transaction(transaction_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_txn_acc ON transaction(account_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_txn_date ON transaction(transaction_date)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_txn_ref ON transaction(transaction_reference_id)")
            logger.info("Indexes created successfully")
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    def _execute_with_timeout(self, sql: str):
        """Run a query on a background thread and hard-cancel it via conn.interrupt() if it
        exceeds QUERY_TIMEOUT_SECONDS. Found necessary the hard way: a self-join with an OR
        join condition (a plausible small-model mistake, e.g. "duplicate reference OR UTR")
        took 938s and 15GB before DuckDB itself gave up with an OOM error on just 500K rows -
        at the 20M-row hackathon scale that class of query could hang the whole app instead of
        failing fast into the repair loop. A single DuckDB connection only ever runs one query
        at a time, so this thread and the caller never touch self.conn concurrently."""
        outcome: Dict[str, Any] = {}

        def run():
            try:
                cursor = self.conn.execute(sql)
                outcome["rows"] = cursor.fetchall()
                outcome["cols"] = [d[0] for d in cursor.description] if cursor.description else []
            except Exception as e:
                outcome["error"] = e

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(timeout=self.query_timeout_seconds)

        if thread.is_alive():
            self.conn.interrupt()
            thread.join(timeout=5)
            raise TimeoutError(
                f"Query exceeded {self.query_timeout_seconds}s and was cancelled - likely a "
                f"pathological join/cross-product, not a transient slowdown"
            )
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("rows", []), outcome.get("cols", [])

    def execute_query(self, sql: str) -> List[Dict[str, Any]]:
        """Execute SQL query and return results as list of dicts"""
        try:
            rows, columns = self._execute_with_timeout(sql)
            data = [dict(zip(columns, row)) for row in rows]
            logger.debug(f"Query executed successfully, returned {len(data)} rows")
            return data
        except Exception as e:
            logger.error(f"Query execution failed: {e}\nSQL: {sql}")
            raise

    def execute_scalar(self, sql: str) -> Any:
        """Execute query that returns a single value"""
        try:
            rows, _ = self._execute_with_timeout(sql)
            return rows[0][0] if rows else None
        except Exception as e:
            logger.error(f"Scalar query failed: {e}\nSQL: {sql}")
            raise
    
    def get_schema_info(self) -> Dict[str, List[str]]:
        """Get schema information for TBX tables"""
        schema = {}
        tables = ["bank", "account", "transaction"]
        
        for table in tables:
            try:
                cols = self.conn.execute(f"DESCRIBE {table}").fetchall()
                schema[table] = [f"{col[0]} ({col[1]})" for col in cols]
            except:
                pass
        
        return schema
    
    def get_dataset_stats(self) -> Dict[str, Any]:
        """Get statistics about the currently loaded dataset"""
        try:
            stats = {
                "dataset": self.dataset,
                "bank_count": self.execute_scalar("SELECT COUNT(*) FROM bank"),
                "account_count": self.execute_scalar("SELECT COUNT(*) FROM account"),
                "transaction_count": self.execute_scalar("SELECT COUNT(*) FROM transaction"),
                "unique_banks": self.execute_scalar("SELECT COUNT(DISTINCT bank_code) FROM account"),
                "total_balance": self.execute_scalar("SELECT SUM(available_balance) FROM account"),
            }
            return stats
        except Exception as e:
            logger.error(f"Failed to get dataset stats: {e}")
            return {}
    
    def switch_dataset(self, dataset: str = "large"):
        """Switch between small and large dataset"""
        if dataset not in ["small", "large"]:
            raise ValueError("Dataset must be 'small' or 'large'")
        
        self.dataset = dataset
        self._load_data_from_csv()
        logger.info(f"Switched to {dataset} dataset")
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Global database instance
_db_instance = None

def get_db() -> FinanceDB:
    """Get or create global database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = FinanceDB()
    return _db_instance
