"""
DuckDB Database Management
Handles financial data loading and query execution
Schema: bank, account, transaction (TBX Finance Assistant)
"""

import os
import duckdb
from pathlib import Path
from typing import Any, List, Dict, Optional
import logging
from encryption import AccountEncryption

logger = logging.getLogger(__name__)

class FinanceDB:
    """DuckDB wrapper for TBX financial data queries.

    Data source is either local CSVs (default, for dev/small/large datasets) or a live
    MySQL instance if MYSQL_HOST/MYSQL_USER/MYSQL_DATABASE env vars are set - useful for
    final verification against a judge-provided database with the same bank/account/
    transaction schema. DuckDB's mysql extension attaches the remote DB and we expose it
    through views named bank/account/transaction, so SQL generation/validation code
    (which only knows about those three unqualified table names) needs no changes.
    """
    
    def __init__(self, db_path: str = "./data/finance.db", dataset: str = "small"):
        """
        Initialize database connection
        Args:
            db_path: Path to DuckDB database file
            dataset: 'small' (10 records) or 'large' (500k+ records), ignored if MySQL is configured
        """
        self.db_path = db_path
        self.dataset = dataset
        self.conn = None
        self.mysql_config = self._read_mysql_config()
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
        """Initialize DuckDB connection and load data (from MySQL if configured, else CSV)"""
        try:
            self.conn = duckdb.connect(self.db_path, read_only=False)
            logger.info(f"Connected to DuckDB: {self.db_path}")
            if self.mysql_config:
                self._load_data_from_mysql()
            else:
                self._load_data_from_csv()
            logger.info("Data loaded successfully")
        except Exception as e:
            logger.error(f"Failed to initialize DuckDB: {e}")
            raise

    def _load_data_from_mysql(self):
        """Attach a live MySQL database via DuckDB's mysql extension and copy its
        bank/account/transaction tables into local DuckDB tables of the same name, for final
        verification against a real judge-provided database instead of the bundled CSV
        datasets. We materialize a snapshot (same pattern as CSV loading) rather than
        exposing live views, since aggregate queries against live mysql-scanner views hit a
        known DuckDB internal error (count_star() binding failure) with this extension."""
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
                for drop_stmt in (f"DROP VIEW IF EXISTS {table_name}", f"DROP TABLE IF EXISTS {table_name}"):
                    try:
                        self.conn.execute(drop_stmt)
                    except Exception:
                        pass  # object doesn't exist or is the other kind - safe to ignore
                self.conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM mysqldb.{table_name}")
                row_count = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                logger.info(f"  ✓ Loaded {table_name} from MySQL: {row_count:,} rows")
                
                # Encrypt account numbers after loading from MySQL
                if table_name == "account":
                    self._encrypt_account_numbers()

            self.conn.execute("DETACH mysqldb")
            self._create_indexes()

        except Exception as e:
            logger.error(f"Failed to attach MySQL database: {e}")
            raise
    
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
                    
                    # Encrypt account numbers if this is the account table
                    if table_name == "account":
                        self._encrypt_account_numbers()
                    
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
    
    def _encrypt_account_numbers(self):
        """Encrypt account numbers in the account table"""
        try:
            # First, ensure the account_number_masked column exists (add if missing)
            try:
                self.conn.execute("ALTER TABLE account ADD COLUMN account_number_masked VARCHAR(20)")
            except:
                pass  # Column already exists
            
            # Get all account numbers
            rows = self.conn.execute("SELECT account_id, account_number FROM account").fetchall()
            
            # Encrypt each account number and update the table
            for account_id, account_number in rows:
                encrypted = AccountEncryption.encrypt_account_number(account_number)
                # Also create a masked display version (XXXXXXXX + last 4 digits)
                masked_display = AccountEncryption.mask_account_number(account_number)
                self.conn.execute(
                    "UPDATE account SET account_number = ?, account_number_masked = ? WHERE account_id = ?",
                    (encrypted, masked_display, account_id)
                )
            
            logger.info(f"  ✓ Encrypted {len(rows)} account numbers in the database")
        except Exception as e:
            logger.error(f"Failed to encrypt account numbers: {e}")
            raise
    
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
    
    def execute_query(self, sql: str) -> List[Dict[str, Any]]:
        """Execute SQL query and return results as list of dicts"""
        try:
            result = self.conn.execute(sql).fetchall()
            columns = [desc[0] for desc in self.conn.description] if self.conn.description else []
            
            # Convert to list of dicts
            data = [dict(zip(columns, row)) for row in result]
            logger.debug(f"Query executed successfully, returned {len(data)} rows")
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
