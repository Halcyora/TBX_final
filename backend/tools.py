"""
Tools for LangGraph
Query execution, anomaly detection, data processing
"""

import logging
import re
from typing import List, Dict, Any, Tuple
from datetime import datetime
import numpy as np
from sklearn.ensemble import IsolationForest
import pandas as pd

from database import get_db, FinanceDB
from sql_validator import SQLValidator, QueryResultValidator

logger = logging.getLogger(__name__)

class QueryExecutor:
    """Executes validated SQL queries"""
    
    @staticmethod
    def execute(sql: str) -> Tuple[bool, Any]:
        """
        Execute SQL query with validation and error handling
        Returns: (success, result or error_message)
        """
        # Validate query first
        is_valid, validation_msg = SQLValidator.validate_query(sql)
        if not is_valid:
            logger.error(f"Query validation failed: {validation_msg}")
            return False, f"Query validation failed: {validation_msg}"
        
        try:
            db = get_db()
            results = db.execute_query(sql)
            # Mask account numbers for security (keep encrypted values for decryption API)
            results = FinanceDB.mask_query_results(results)
            logger.info(f"Query executed successfully, returned {len(results)} rows")
            return True, results
        
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            return False, f"Query execution error: {str(e)}"
    
    @staticmethod
    def execute_scalar(sql: str) -> Tuple[bool, Any]:
        """Execute query returning single value"""
        is_valid, validation_msg = SQLValidator.validate_query(sql)
        if not is_valid:
            return False, validation_msg
        
        try:
            db = get_db()
            result = db.execute_scalar(sql)
            return True, result
        except Exception as e:
            return False, str(e)


class AnomalyDetector:
    """Detects anomalous transactions using hybrid approach"""
    
    def __init__(self, zscore_threshold: float = 2.0, multiplier_threshold: float = 3.0):
        self.zscore_threshold = zscore_threshold
        self.multiplier_threshold = multiplier_threshold
    
    def detect_anomalies(self, results: List[Dict[str, Any]], 
                        amount_column: str = "amount",
                        vendor_column: str = "vendor_id") -> Dict[str, Any]:
        """
        Detect anomalies using hybrid approach:
        1. Statistical (Z-score)
        2. Business rules (multiplier)
        3. Context awareness
        """
        if not results or len(results) < 2:
            return {"anomalies": [], "method": "insufficient_data"}
        
        anomalies = []
        
        try:
            # Convert to DataFrame for easier analysis
            df = pd.DataFrame(results)
            
            # Check if amount column exists
            if amount_column not in df.columns:
                return {"anomalies": [], "method": "amount_column_not_found"}
            
            # Ensure amount is numeric
            df[amount_column] = pd.to_numeric(df[amount_column], errors='coerce')
            
            # Skip null amounts
            df_clean = df[df[amount_column].notna()].copy()
            
            if len(df_clean) < 2:
                return {"anomalies": [], "method": "insufficient_data"}
            
            # Method 1: Z-score detection
            z_anomalies = self._zscore_detection(df_clean, amount_column)
            
            # Method 2: Multiplier detection (vendor-specific)
            mult_anomalies = self._multiplier_detection(df_clean, amount_column, vendor_column)
            
            # Method 3: Isolation Forest (if enough data)
            if len(df_clean) >= 10:
                iso_anomalies = self._isolation_forest_detection(df_clean, amount_column)
            else:
                iso_anomalies = []
            
            # Combine and deduplicate
            all_anomalies = z_anomalies + mult_anomalies + iso_anomalies
            unique_anomalies = self._deduplicate_anomalies(all_anomalies)
            
            return {
                "anomalies": unique_anomalies,
                "count": len(unique_anomalies),
                "method": "hybrid",
                "stats": {
                    "mean": float(df_clean[amount_column].mean()),
                    "median": float(df_clean[amount_column].median()),
                    "std": float(df_clean[amount_column].std()),
                    "min": float(df_clean[amount_column].min()),
                    "max": float(df_clean[amount_column].max())
                }
            }
        
        except Exception as e:
            logger.error(f"Anomaly detection error: {e}")
            return {"anomalies": [], "error": str(e)}
    
    def _zscore_detection(self, df: pd.DataFrame, amount_col: str) -> List[Dict[str, Any]]:
        """Statistical anomaly detection using Z-score"""
        anomalies = []
        
        mean = df[amount_col].mean()
        std = df[amount_col].std()
        
        if std == 0:
            return anomalies
        
        df['zscore'] = np.abs((df[amount_col] - mean) / std)
        outliers = df[df['zscore'] > self.zscore_threshold]
        
        for _, row in outliers.iterrows():
            anomalies.append({
                "type": "statistical_zscore",
                "row": row.to_dict(),
                "reason": f"Z-score: {row['zscore']:.2f} (threshold: {self.zscore_threshold})",
                "severity": "high" if row['zscore'] > self.zscore_threshold * 1.5 else "medium"
            })
        
        return anomalies
    
    def _multiplier_detection(self, df: pd.DataFrame, amount_col: str, 
                             vendor_col: str) -> List[Dict[str, Any]]:
        """Business rule detection: amounts > 3x vendor average"""
        anomalies = []
        
        if vendor_col not in df.columns:
            return anomalies
        
        for vendor in df[vendor_col].unique():
            vendor_data = df[df[vendor_col] == vendor][amount_col]
            
            if len(vendor_data) < 2:
                continue
            
            avg = vendor_data.mean()
            threshold = avg * self.multiplier_threshold
            
            outliers = df[(df[vendor_col] == vendor) & (df[amount_col] > threshold)]
            
            for _, row in outliers.iterrows():
                ratio = row[amount_col] / avg if avg > 0 else 0
                anomalies.append({
                    "type": "business_multiplier",
                    "row": row.to_dict(),
                    "reason": f"{ratio:.1f}x vendor average (avg: ${avg:.2f})",
                    "severity": "high" if ratio > self.multiplier_threshold * 1.5 else "medium"
                })
        
        return anomalies
    
    def _isolation_forest_detection(self, df: pd.DataFrame, amount_col: str) -> List[Dict[str, Any]]:
        """Machine learning based detection: Isolation Forest"""
        anomalies = []
        
        try:
            X = df[[amount_col]].values
            
            # Isolation Forest needs at least 2 samples
            if len(X) < 2:
                return anomalies
            
            iso_forest = IsolationForest(contamination=0.1, random_state=42)
            predictions = iso_forest.fit_predict(X)
            
            anomaly_indices = np.where(predictions == -1)[0]
            
            for idx in anomaly_indices:
                anomalies.append({
                    "type": "ml_isolation_forest",
                    "row": df.iloc[idx].to_dict(),
                    "reason": "Identified as anomaly by ML model (Isolation Forest)",
                    "severity": "medium"
                })
        
        except Exception as e:
            logger.warning(f"Isolation Forest detection failed: {e}")
        
        return anomalies
    
    def _deduplicate_anomalies(self, anomalies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate anomalies detected by multiple methods"""
        unique = {}
        
        for anomaly in anomalies:
            # Use transaction_id or amount+date as key
            row = anomaly['row']
            key = (row.get('transaction_id') or str(row.get('payout_id')) or 
                  f"{row.get('amount')}_{row.get('transaction_date')}")
            
            if key not in unique:
                unique[key] = anomaly
            else:
                # Keep the more severe one
                if anomaly['severity'] == 'high':
                    unique[key] = anomaly
        
        return list(unique.values())


class DataExporter:
    """Export query results to various formats"""
    
    @staticmethod
    def to_csv(results: List[Dict[str, Any]], filename: str = "export.csv") -> Tuple[bool, str]:
        """Export results to CSV"""
        try:
            if not results:
                return False, "No data to export"
            
            df = pd.DataFrame(results)
            df.to_csv(filename, index=False)
            logger.info(f"Exported {len(results)} rows to {filename}")
            return True, filename
        
        except Exception as e:
            logger.error(f"CSV export failed: {e}")
            return False, str(e)
    
    @staticmethod
    def format_results_table(results: List[Dict[str, Any]], max_rows: int = 10) -> str:
        """Format results as readable table"""
        if not results:
            return "No results"
        
        df = pd.DataFrame(results[:max_rows])
        
        # Format numbers with commas/decimals
        for col in df.columns:
            if df[col].dtype in ['float64', 'int64']:
                df[col] = df[col].apply(lambda x: f"${x:,.2f}" if isinstance(x, float) else f"{x:,}")
        
        table_str = df.to_string(index=False)
        
        if len(results) > max_rows:
            table_str += f"\n... and {len(results) - max_rows} more rows"
        
        return table_str


class ContextManager:
    """Manage conversation context and summaries"""
    
    @staticmethod
    def summarize_turn(question: str, answer: str, max_length: int = 150) -> str:
        """Summarize a conversation turn for context retention"""
        # Simple summary: first sentence of Q + main number from A
        q_summary = (question or "").split('.')[0][:100]
        
        # Extract key numbers from answer (handles $, commas, decimals)
        numbers = re.findall(r"\$?-?\d[\d,]*\.?\d*", answer or "")
        a_summary = f"Result: {', '.join(numbers[:2])}" if numbers else "Result obtained"
        
        return f"{q_summary} -> {a_summary}"[:max_length]
    
    @staticmethod
    def compress_context(turns: List[Dict[str, Any]], max_turns: int = 3) -> List[Dict[str, Any]]:
        """Keep last N full Q&A turns, summarize older ones"""
        if len(turns) <= max_turns:
            return turns
        
        # Keep last N full turns
        recent = turns[-max_turns:]
        
        # Summarize older turns (each turn is {"question", "answer", ...})
        older = turns[:-max_turns]
        summaries = []
        for t in older:
            if t.get("role") == "summary":
                summaries.append(t)  # already compressed, keep as-is
            else:
                summaries.append({
                    "role": "summary",
                    "content": ContextManager.summarize_turn(t.get("question", ""), t.get("answer", ""))
                })
        
        return summaries + recent

    @staticmethod
    def format_history_for_prompt(turns: List[Dict[str, Any]]) -> str:
        """Render compressed conversation history as a text block for LLM prompts"""
        if not turns:
            return ""
        
        lines = ["Previous conversation (for context; only use if relevant to the new question):"]
        for t in turns:
            if t.get("role") == "summary":
                lines.append(f"- {t.get('content', '')}")
            else:
                question = t.get("question", "")
                answer = (t.get("answer", "") or "")[:200]
                lines.append(f'- User asked: "{question}" -> Answered: "{answer}"')
        lines.append("")  # blank line separator before the new question
        
        return "\n".join(lines) + "\n"
