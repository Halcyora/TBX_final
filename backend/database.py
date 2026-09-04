"""
DuckDB Database Management
Handles financial data loading and query execution
"""

import duckdb
from pathlib import Path
from typing import Any, List, Dict
import logging

logger = logging.getLogger(__name__)

class FinanceDB:
    """DuckDB wrapper for financial data queries"""
    
    def __init__(self, db_path: str = "./data/finance.db"):
        self.db_path = db_path
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
        """Load CSV files into DuckDB tables"""
        data_dir = Path("./data")
        
        # Tables to load with their CSV file names
        tables = {
            "transactions": "transactions.csv",
            "vendor_payouts": "vendor_payouts.csv",
            "reconciliation_status": "reconciliation_status.csv",
            "chart_of_accounts": "chart_of_accounts.csv",
            "vendor_list": "vendor_list.csv",
        }
        
        for table_name, csv_file in tables.items():
            csv_path = data_dir / csv_file
            if csv_path.exists():
                try:
                    # Read CSV into table
                    self.conn.execute(f"""
                        CREATE OR REPLACE TABLE {table_name} AS
                        SELECT * FROM read_csv_auto('{csv_path}')
                    """)
                    
                    # Get row count
                    row_count = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                    logger.info(f"Loaded {table_name}: {row_count} rows")
                    
                except Exception as e:
                    logger.error(f"Failed to load {table_name}: {e}")
                    raise
            else:
                logger.warning(f"CSV file not found: {csv_path}")
        
        # Create useful indexes for faster queries
        self._create_indexes()
    
    def _create_indexes(self):
        """Create indexes on commonly queried columns"""
        try:
            self.conn.execute("CREATE INDEX idx_txn_vendor ON transactions(vendor_id)")
            self.conn.execute("CREATE INDEX idx_txn_date ON transactions(transaction_date)")
            self.conn.execute("CREATE INDEX idx_txn_status ON transactions(status)")
            self.conn.execute("CREATE INDEX idx_payout_vendor ON vendor_payouts(vendor_id)")
            self.conn.execute("CREATE INDEX idx_payout_date ON vendor_payouts(payout_date)")
            self.conn.execute("CREATE INDEX idx_recon_txn ON reconciliation_status(transaction_id)")
            logger.info("Indexes created successfully")
        except Exception as e:
            logger.warning(f"Index creation warning (might already exist): {e}")
    
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
        """Get schema information for all tables"""
        schema = {}
        tables = ["transactions", "vendor_payouts", "reconciliation_status", 
                  "chart_of_accounts", "vendor_list"]
        
        for table in tables:
            try:
                cols = self.conn.execute(f"DESCRIBE {table}").fetchall()
                schema[table] = [f"{col[0]} ({col[1]})" for col in cols]
            except:
                pass
        
        return schema
    
    def get_vendor_stats(self, vendor_id: str) -> Dict[str, Any]:
        """Get statistics for a specific vendor"""
        try:
            stats = self.conn.execute(f"""
                SELECT 
                    vendor_id,
                    COUNT(*) as total_transactions,
                    SUM(amount) as total_amount,
                    AVG(amount) as avg_amount,
                    MAX(amount) as max_amount,
                    MIN(amount) as min_amount,
                    STDDEV(amount) as stddev_amount
                FROM transactions
                WHERE vendor_id = '{vendor_id}'
                GROUP BY vendor_id
            """).fetchone()
            
            if stats:
                cols = ["vendor_id", "total_transactions", "total_amount", "avg_amount", 
                        "max_amount", "min_amount", "stddev_amount"]
                return dict(zip(cols, stats))
            return {}
        except Exception as e:
            logger.error(f"Failed to get vendor stats: {e}")
            return {}
    
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
