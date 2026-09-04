import React from 'react';
import { FinanceAnswer } from '../lib/types';
import styles from '../styles/ResultsPanel.module.css';

interface ResultsPanelProps {
  result: FinanceAnswer;
}

export default function ResultsPanel({ result }: ResultsPanelProps) {
  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <h3>💡 Answer Details</h3>
        <div className={`${styles.confidence} ${styles[result.confidence_band]}`}>
          {result.confidence_band.toUpperCase()} CONFIDENCE
          <span className={styles.score}>
            {(result.confidence_score * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      {result.message && (
        <div className={styles.section}>
          <h4>Answer</h4>
          <p>{result.message}</p>
        </div>
      )}

      {result.grounding_info && (
        <div className={styles.section}>
          <h4>📊 Grounding Info</h4>
          <details>
            <summary>SQL Query</summary>
            <pre><code>{result.grounding_info.sql_query}</code></pre>
          </details>
          <p className={styles.groundingText}>
            Data source: Verified execution against database
          </p>
        </div>
      )}

      {result.anomalies_detected && result.anomalies_detected.length > 0 && (
        <div className={styles.section}>
          <h4>🚨 Anomalies Detected</h4>
          <ul className={styles.anomalyList}>
            {result.anomalies_detected.map((anomaly, idx) => (
              <li key={idx} className={styles[anomaly.severity]}>
                <strong>{anomaly.transaction_id}:</strong> {anomaly.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.export_available && (
        <div className={styles.section}>
          <button className={styles.exportButton}>
            💾 Export as CSV
          </button>
        </div>
      )}
    </div>
  );
}
