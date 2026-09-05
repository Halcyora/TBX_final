"""
DuckDB Database Management
Handles financial data loading and query execution
Schema: bank, account, transaction (TBX Finance Assistant)
"""

import duckdb
from pathlib import Path
from typing import Any, List, Dict
import logging

logger = logging.getLogger(__name__)

class FinanceDB:
    """DuckDB wrapper for TBX financial data queries"""
    
    def __init__(self, db_path: str = "./data/finance.db", dataset: str = "small"):
        """
        Initialize database connection
        Args:
            db_path: Path to DuckDB database file
            dataset: 'small' (10 records) or 'large' (500k+ records)
        """
        self.db_path = db_path
        self.dataset = dataset
        self.conn = None
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
            data_dir = Path("./data/large")
        else:  # default to small
            data_dir = Path("./data")
        
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
                "total_balance": self.execute_scalar("SELECT SUM(CAST(available_balance AS DECIMAL)) FROM account"),
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
