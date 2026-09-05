"""
Database Management
Handles financial data loading and query execution
Schema: bank, account, transaction (TBX Finance Assistant)
"""

import os
import re
import time
import duckdb
import pymysql
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Safety cap for queries with no explicit LIMIT, so a query like "SELECT * FROM transaction"
# can't pull the entire (10M+ row) transaction table into memory/over the wire.
DEFAULT_ROW_CAP = 10000

# How long to cache query results in memory. Aggregate queries (COUNT/SUM) against a live
# remote MySQL table with 10M+ rows require a full table scan on the server and can take
# 30+ seconds; caching avoids repeating that scan for the same/repeated question within
# this window. Set to 0 to disable caching.
QUERY_CACHE_TTL_SECONDS = float(os.getenv("QUERY_CACHE_TTL_SECONDS", "60"))


class MySQLConnectionAdapter:
    """Wraps a pymysql connection with the same chainable execute(...).fetchall()/.description
    interface DuckDB's connection exposes, so the rest of the app (sql_validator, tools, main)
    needs no changes whether it's talking to local DuckDB or live MySQL. Queries run directly
    against MySQL - no local copy and none of DuckDB's mysql-extension aggregate bugs."""

    def __init__(self, cfg: Dict[str, str]):
        self._connection = pymysql.connect(
            host=cfg["host"],
            port=int(cfg["port"]),
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            autocommit=True,
        )
        self._cursor = None

    def execute(self, sql: str, params=None):
        self._cursor = self._connection.cursor()
        self._cursor.execute(sql.replace("?", "%s"), params)
        return self

    def executemany(self, sql: str, seq_of_params):
        self._cursor = self._connection.cursor()
        self._cursor.executemany(sql.replace("?", "%s"), seq_of_params)
        return self

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchone(self):
        return self._cursor.fetchone()

    @property
    def description(self):
        return self._cursor.description if self._cursor else None

    def close(self):
        self._connection.close()


class FinanceDB:
    """Wrapper for TBX financial data queries.

    Data source is either local CSVs loaded into DuckDB (default, for dev/small/large
    datasets) or a live MySQL instance if MYSQL_HOST/MYSQL_USER/MYSQL_DATABASE env vars are
    set - useful for final verification against a judge-provided database with the same
    bank/account/transaction schema. When MySQL is configured we connect to it directly via
    pymysql (see MySQLConnectionAdapter) and query it live - no local copy/materialization
    step, so startup is instant and there's no dependency on DuckDB's mysql extension.
    """
    
    def __init__(self, db_path: str = "./data/finance.db", dataset: str = "small"):
        """
        Initialize database connection
        Args:
            db_path: Path to DuckDB database file (only used when MySQL isn't configured)
            dataset: 'small' (10 records) or 'large' (500k+ records), ignored if MySQL is configured
        """
        self.db_path = db_path
        self.dataset = dataset
        self.conn = None
        self.mysql_config = self._read_mysql_config()
        self._query_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self.initialize()

    @staticmethod
    def _read_mysql_config() -> Optional[Dict[str, str]]:
        """Read MySQL connection settings from env vars, if a host+user+database are provided"""
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
        """Connect to the configured data source: live MySQL (direct, via pymysql) if
        configured, else DuckDB loaded from local CSVs."""
        try:
            if self.mysql_config:
                self._connect_live_mysql()
            else:
                self.conn = duckdb.connect(self.db_path, read_only=False)
                logger.info(f"Connected to DuckDB: {self.db_path}")
                self._load_data_from_csv()
            logger.info("Data loaded successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def _connect_live_mysql(self):
        """Connect directly to MySQL via pymysql and query it live - bank/account/transaction
        are queried straight from MySQL with no local copy, so this is instant regardless of
        table size and unaffected by DuckDB's mysql-extension aggregate bug. Startup only does
        a cheap existence check per table (not a COUNT(*)), so a 10M+ row transaction table
        doesn't add scan latency to app startup - actual counts are fetched on demand per query."""
        cfg = self.mysql_config
        logger.info(f"Connecting directly to MySQL at {cfg['host']}:{cfg['port']}/{cfg['database']}")
        self.conn = MySQLConnectionAdapter(cfg)
        for table_name in ("bank", "account", "transaction"):
            self.conn.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone()
            logger.info(f"  ✓ Connected to {table_name} in MySQL (queried live, no local copy)")
    
    def _load_data_from_csv(self):
        """Load CSV files into DuckDB tables from selected dataset"""
        # Determine dataset directory. CSVs live in the repo-root ./data folder,
        # not backend/data (which only holds finance.db + sessions_store.json).
        repo_data_dir = Path(__file__).resolve().parent.parent / "data"
        if self.dataset == "large":
            data_dir = repo_data_dir / "large"
        else:  # default to small
            data_dir = repo_data_dir / "small"
        
        # TBX Schema: bank, account, transaction
        tables = {
            "bank": "bank.csv",
            "account": "account.csv",
            "transaction": "transaction.csv",
        }
        
        logger.info(f"Loading {self.dataset} dataset from {data_dir}")
        
        for table_name, csv_file in tables.items():
            csv_path = data_dir / csv_file
            if csv_path.exists():
                try:
                    # Read CSV into table
                    self.conn.execute(f"""
                        CREATE OR REPLACE TABLE {table_name} AS
                        SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
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
    
    @staticmethod
    def _apply_row_cap(sql: str, cap: int = DEFAULT_ROW_CAP) -> str:
        """Wrap queries that have no top-level LIMIT clause in a capped subquery, so a
        query against the transaction table can't return millions of rows into memory."""
        stripped = sql.strip().rstrip(";")
        if re.search(r'\bLIMIT\s+\d+', stripped, re.IGNORECASE):
            return stripped
        return f"SELECT * FROM ({stripped}) AS _capped_result LIMIT {cap}"

    def execute_query(self, sql: str) -> List[Dict[str, Any]]:
        """Execute SQL query and return results as list of dicts. Cached briefly (see
        QUERY_CACHE_TTL_SECONDS) since repeated aggregate queries against the live 10M+ row
        transaction table are expensive full-table scans on the remote MySQL server."""
        capped_sql = self._apply_row_cap(sql)

        if QUERY_CACHE_TTL_SECONDS > 0:
            cached = self._query_cache.get(capped_sql)
            if cached and (time.time() - cached[0]) < QUERY_CACHE_TTL_SECONDS:
                logger.debug("Query cache hit")
                return cached[1]

        try:
            result = self.conn.execute(capped_sql).fetchall()
            columns = [desc[0] for desc in self.conn.description] if self.conn.description else []
            
            # Convert to list of dicts
            data = [dict(zip(columns, row)) for row in result]
            logger.debug(f"Query executed successfully, returned {len(data)} rows")

            if QUERY_CACHE_TTL_SECONDS > 0:
                self._query_cache[capped_sql] = (time.time(), data)

            return data
        except Exception as e:
            logger.error(f"Query execution failed: {e}\nSQL: {sql}")
            raise
    
    def execute_scalar(self, sql: str) -> Any:
        """Execute query that returns a single value"""
        try:
            result = self.conn.execute(sql).fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Scalar query failed: {e}\nSQL: {sql}")
            raise
    
    @staticmethod
    def mask_query_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Mask account numbers in query results for display.
        Uses pre-stored masked display value and keeps encrypted version for decryption."""
        if not results:
            return results
        
        masked_results = []
        for row in results:
            masked_row = row.copy()
            
            # Check if this row has an account_number field (encrypted)
            if "account_number" in masked_row:
                encrypted_value = masked_row["account_number"]
                # Use the pre-stored masked display (XXXXXXXX + last 4 digits)
                display_value = masked_row.get("account_number_masked", "XXXXXXXX")
                
                # Set both fields for the response
                masked_row["account_number_display"] = display_value
                masked_row["account_number_encrypted"] = encrypted_value
            
            masked_results.append(masked_row)
        
        return masked_results
    
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
                "dataset": "mysql" if self.mysql_config else self.dataset,
                "bank_count": self.execute_scalar("SELECT COUNT(*) FROM bank"),
                "account_count": self.execute_scalar("SELECT COUNT(*) FROM account"),
                "transaction_count": self.execute_scalar("SELECT COUNT(*) FROM transaction"),
                "unique_banks": self.execute_scalar("SELECT COUNT(DISTINCT bank_code) FROM account"),
                "total_balance": self.execute_scalar("SELECT SUM(CAST(available_balance AS DECIMAL)) FROM account"),
            }
            return stats
        except Exception as e:
            logger.error(f"Failed to get dataset stats: {e}")
            return {}
    
    def switch_dataset(self, dataset: str = "large"):
        """Switch between small and large CSV dataset. Not applicable when connected to MySQL."""
        if self.mysql_config:
            raise ValueError("Cannot switch CSV dataset while connected to a live MySQL database")
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
