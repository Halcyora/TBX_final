import React, { useState } from 'react';
import { FinanceAnswer } from '../lib/types';
import styles from '../styles/ResultsPanel.module.css';

interface ResultsPanelProps {
  result: FinanceAnswer;
}

export default function ResultsPanel({ result }: ResultsPanelProps) {
  const rows = result.query_results || [];
  // Filter out account_number_display since we handle it via encrypted cell
  const allColumns = rows.length > 0 ? Object.keys(rows[0]) : [];
  const columns = allColumns.filter((col) => col !== 'account_number_display');
  const [exporting, setExporting] = useState(false);
  const [showGrounding, setShowGrounding] = useState(false);
  const [decryptionCode, setDecryptionCode] = useState('');
  const [decryptedValues, setDecryptedValues] = useState<Record<string, string>>({});
  const [decryptingIndex, setDecryptingIndex] = useState<number | null>(null);
  const [decryptError, setDecryptError] = useState<string | null>(null);

  // Check if any rows have encrypted account numbers
  const hasEncryptedAccounts = rows.some((row) => row.account_number_encrypted);

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

  const handleDecrypt = async (rowIndex: number, encryptedValue: string) => {
    if (!decryptionCode.trim()) {
      setDecryptError('Please enter a decryption code');
      return;
    }

    setDecryptingIndex(rowIndex);
    setDecryptError(null);

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/decrypt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          encrypted_account_number: encryptedValue,
          decryption_code: decryptionCode,
        }),
      });

      if (!response.ok) throw new Error('Decryption failed');

      const data = await response.json();
      if (data.success) {
        setDecryptedValues((prev) => ({
          ...prev,
          [rowIndex]: data.account_number,
        }));
        setDecryptError(null);
      } else {
        setDecryptError(data.error || 'Decryption failed');
      }
    } catch (error) {
      console.error('Decryption error:', error);
      setDecryptError('Failed to decrypt. Please try again.');
    } finally {
      setDecryptingIndex(null);
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
                    {columns.map((col) => {
                      // Handle account_number_encrypted specially
                      if (col === 'account_number_encrypted') {
                        const decrypted = decryptedValues[idx];
                        return (
                          <td key={col} className={styles.encryptedCell}>
                            {decrypted ? (
                              <span className={styles.decrypted}>{decrypted}</span>
                            ) : (
                              <>
                                <span className={styles.encrypted}>{formatCellValue(row[col])}</span>
                                <button
                                  className={styles.decryptBtn}
                                  onClick={() => handleDecrypt(idx, row[col])}
                                  disabled={decryptingIndex === idx || !decryptionCode.trim()}
                                  title="Click to decrypt with your code"
                                >
                                  {decryptingIndex === idx ? '🔓 ...' : '🔒 Decrypt'}
                                </button>
                              </>
                            )}
                          </td>
                        );
                      }
                      return <td key={col}>{formatCellValue(row[col])}</td>;
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {hasEncryptedAccounts && (
        <div className={styles.decryptionPanel}>
          <h4>🔐 Decryption Panel</h4>
          <p className={styles.decryptionInfo}>
            This query contains encrypted account numbers. Enter your decryption code to reveal them.
          </p>
          <div className={styles.decryptionForm}>
            <input
              type="password"
              placeholder="Enter your decryption code"
              value={decryptionCode}
              onChange={(e) => {
                setDecryptionCode(e.target.value);
                setDecryptError(null);
              }}
              onKeyPress={(e) => {
                if (e.key === 'Enter' && decryptingIndex === null) {
                  // Decrypt the first encrypted value
                  const firstEncrypted = rows.find((r) => r.account_number_encrypted);
                  if (firstEncrypted) {
                    const idx = rows.indexOf(firstEncrypted);
                    handleDecrypt(idx, firstEncrypted.account_number_encrypted);
                  }
                }
              }}
              className={styles.decryptionInput}
            />
            {decryptError && <span className={styles.decryptError}>❌ {decryptError}</span>}
            {Object.keys(decryptedValues).length > 0 && (
              <span className={styles.decryptSuccess}>✅ Successfully decrypted {Object.keys(decryptedValues).length} account number(s)</span>
            )}
          </div>
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
