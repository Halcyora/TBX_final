import React, { useState } from 'react';
import { FinanceAnswer } from '../lib/types';
import styles from '../styles/ResultsPanel.module.css';

interface ResultsPanelProps {
  result: FinanceAnswer;
}

export default function ResultsPanel({ result }: ResultsPanelProps) {
  const rows = result.query_results || [];
  const columns = rows.length > 0 ? Object.keys(rows[0]) : [];
  const [exporting, setExporting] = useState(false);
  const [showGrounding, setShowGrounding] = useState(false);

  const anomaliesById = new Map(
    (result.anomalies_detected || []).map((a) => [String(a.transaction_id), a])
  );
  const idColumn = columns.find((col) => col === 'transaction_id' || col === 'payout_id');

  const handleExport = async () => {
    setExporting(true);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: result.session_id, format: 'csv' }),
      });
      if (!response.ok) throw new Error('Export failed');

      // Trigger a real browser download (saves to the user's default Downloads folder)
      // rather than just leaving the CSV sitting server-side.
      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition');
      const match = disposition?.match(/filename="?([^"]+)"?/);
      const filename = match ? match[1] : 'export.csv';

      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to export CSV:', error);
      alert('Failed to export CSV. Please try again.');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <div className={`${styles.confidence} ${styles[result.confidence_band]}`}>
          {result.confidence_band.toUpperCase()} CONFIDENCE
          <span className={styles.score}>
            {(result.confidence_score * 100).toFixed(0)}%
          </span>
        </div>
        {result.export_available && (
          <button className={styles.exportButton} onClick={handleExport} disabled={exporting}>
            {exporting ? 'Exporting...' : '💾 Export as CSV'}
          </button>
        )}
      </div>

      {rows.length > 0 && (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                {idColumn && <th></th>}
                {columns.map((col) => (
                  <th key={col}>{col.replace(/_/g, ' ')}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => {
                const rowId = idColumn ? String(row[idColumn]) : undefined;
                const anomaly = rowId ? anomaliesById.get(rowId) : undefined;
                return (
                  <tr key={idx} className={anomaly ? styles[`anomalyRow_${anomaly.severity}`] : undefined} title={anomaly?.reason}>
                    {idColumn && <td className={styles.anomalyFlag}>{anomaly ? '🚨' : ''}</td>}
                    {columns.map((col) => (
                      <td key={col}>{formatCellValue(row[col])}</td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {result.grounding_info && (
        <div className={styles.section}>
          <div className={styles.tabBar}>
            <button
              className={`${styles.tabButton} ${showGrounding ? styles.tabActive : ''}`}
              onClick={() => setShowGrounding((prev) => !prev)}
              title="SQL query and data grounding information"
            >
              📊 Grounding Info {showGrounding ? '▲' : '▼'}
            </button>
          </div>

          {showGrounding && (
            <>
              <pre><code>{result.grounding_info.sql_query}</code></pre>
              <p className={styles.groundingText}>
                Data source: {result.grounding_info.data_source || 'Verified execution against database'}
              </p>
            </>
          )}
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
    </div>
  );
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'number') {
    return value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }
  return String(value);
}
