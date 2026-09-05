"""
DuckDB Database Management
Handles financial data loading and query execution
Schema: bank, account, transaction (TBX Finance Assistant)
"""

import os
import duckdb
import threading
from pathlib import Path
from typing import Any, List, Dict, Optional
import logging

from crypto_utils import encrypt_value, decrypt_value
from query_cache import flush_all

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
            dataset: 'small' (10 records) or 'large' (500k+ records), ignored if MySQL is configured
        """
        self.db_path = db_path
        self.dataset = dataset
        self.conn = None
        self.query_timeout_seconds = float(os.getenv("QUERY_TIMEOUT_SECONDS", "15"))
        self.mysql_config = self._read_mysql_config()
        self.initialize()

    @staticmethod
    def _read_mysql_config() -> Optional[Dict[str, str]]:
        """Read MySQL connection settings from env vars, if a host+user+database are provided.
        For final verification against a judge-provided database with the same bank/account/
        transaction schema, instead of the bundled CSV datasets."""
        host = os.getenv("MYSQL_HOST")
        user = os.getenv("MYSQL_USER")
        database = os.getenv("MYSQL_DATABASE")
        if not (host and user and database):
            return None
        return {
            "host": host,
            "port": os.getenv("MYSQL_PORT", "3306"),
            "user": user,
            "password": os.getenv("MYSQL_PASSWORD", ""),
            "database": database,
        }

    def initialize(self):
        """Initialize DuckDB connection and load data (from MySQL if configured, else CSV)"""
        try:
            self.conn = duckdb.connect(self.db_path, read_only=False)
            logger.info(f"Connected to DuckDB: {self.db_path}")
            if self.mysql_config:
                self._load_data_from_mysql()
            else:
                self._load_data_from_csv()
            # A verified-query cache entry from a previous run/dataset isn't safe to replay
            # against whatever just got loaded - see switch_dataset()'s flush for the same reason.
            flush_all()
            logger.info("Data loaded successfully")
        except Exception as e:
            logger.error(f"Failed to initialize DuckDB: {e}")
            raise

    def _load_data_from_mysql(self):
        """Attach a live MySQL database via DuckDB's mysql extension and copy its
        bank/account/transaction tables into local DuckDB tables of the same name, for final
        verification against a real judge-provided database instead of the bundled CSV
        datasets. Materializes a snapshot (same pattern as CSV loading) rather than exposing
        live views, since aggregate queries against live mysql-scanner views hit a known DuckDB
        internal error (count_star() binding failure) with this extension.

        All three tables are loaded FIRST, then encrypted in one separate pass at the end -
        deliberately not interleaved (encrypting account right after it loads, mid-loop, before
        `transaction` exists) the way an earlier version of this did, which queried the
        transaction table before it had been created."""
        cfg = self.mysql_config
        logger.info(f"Connecting to MySQL at {cfg['host']}:{cfg['port']}/{cfg['database']} for final verification")

        try:
            self.conn.execute("INSTALL mysql")
            self.conn.execute("LOAD mysql")

            conn_parts = [f"host={cfg['host']}", f"port={cfg['port']}", f"user={cfg['user']}", f"db={cfg['database']}"]
            if cfg["password"]:
                conn_parts.insert(3, f"passwd={cfg['password']}")
            conn_string = " ".join(conn_parts)
            self.conn.execute(f"ATTACH '{conn_string}' AS mysqldb (TYPE mysql)")

            for table_name in ("bank", "account", "transaction"):
                for drop_stmt in (f'DROP VIEW IF EXISTS "{table_name}"', f'DROP TABLE IF EXISTS "{table_name}"'):
                    try:
                        self.conn.execute(drop_stmt)
                    except Exception:
                        pass  # object doesn't exist or is the other kind - safe to ignore
                self.conn.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM mysqldb."{table_name}"')
                row_count = self.conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
                logger.info(f"  ✓ Loaded {table_name} from MySQL: {row_count:,} rows")

            self.conn.execute("DETACH mysqldb")
            self._encrypt_sensitive_columns()
            self._create_indexes()

        except Exception as e:
            logger.error(f"Failed to attach MySQL database: {e}")
            raise

    def _encrypt_sensitive_columns(self):
        """Encrypt account.account_number and transaction.utr_number (AES-256-GCM, see
        crypto_utils.py) for any freshly-ingested plaintext values - the judge-provided MySQL
        data arrives plaintext. Skips values that are already ciphertext (idempotent, safe to
        call again e.g. after a restart)."""
        account_rows = self.conn.execute("SELECT account_id, account_number FROM account").fetchall()
        encrypted_count = 0
        for account_id, account_number in account_rows:
            # decrypt_value() is a no-op passthrough for anything that isn't valid ciphertext
            # for our key - if it comes back unchanged, this is plaintext that needs encrypting.
            if not account_number or decrypt_value(account_number) != account_number:
                continue
            self.conn.execute(
                "UPDATE account SET account_number = ? WHERE account_id = ?",
                (encrypt_value(account_number), account_id),
            )
            encrypted_count += 1
        logger.info(f"  ✓ Encrypted {encrypted_count} account number(s)")

        utr_rows = self.conn.execute(
            'SELECT transaction_id, utr_number FROM "transaction" WHERE utr_number IS NOT NULL'
        ).fetchall()
        encrypted_utr_count = 0
        for transaction_id, utr_number in utr_rows:
            if not utr_number or decrypt_value(utr_number) != utr_number:
                continue
            self.conn.execute(
                'UPDATE "transaction" SET utr_number = ? WHERE transaction_id = ?',
                (encrypt_value(utr_number), transaction_id),
            )
            encrypted_utr_count += 1
        logger.info(f"  ✓ Encrypted {encrypted_utr_count} UTR number(s)")
    
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
        # A cached SQL query verified against the old dataset isn't safe to replay against the
        # new one - different data, even though the SQL itself would still be schema-valid.
        flush_all()
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
