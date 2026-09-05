import React from 'react';
import styles from '../styles/ResultsPanel.module.css';

const STEP_LABELS: Record<string, string> = {
  classification: '🔍 Classifying query',
  clarification_requested: '❓ Requesting clarification',
  sql_generation: '🔨 Generating SQL',
  sql_validation: '✓ Validating SQL',
  query_execution: '⚙️ Executing query',
  anomaly_detection: '⚠️ Detecting anomalies',
  response_formatting: '📝 Formatting response',
  export: '💾 Preparing export',
};

interface StepsListProps {
  stages: string[];
  details?: Record<string, string>;
}

export default function StepsList({ stages, details }: StepsListProps) {
  if (!stages || stages.length === 0) {
    return <p className={styles.groundingText}>No pipeline steps recorded for this turn.</p>;
  }

  return (
    <ol className={styles.stepsList}>
      {stages.map((stage, idx) => (
        <li key={idx} className={styles.stepItem}>
          <div className={styles.stepHeader}>
            <span className={styles.stepCheck}>✓</span>
            {STEP_LABELS[stage] || stage}
          </div>
          {details?.[stage] && (
            <div className={styles.stepDetail}>
              {/* Format SQL queries and other multi-line content */}
              {details[stage].includes('SQL Query:') ? (
                <pre style={{ fontSize: '0.85rem', overflow: 'auto', maxHeight: '200px' }}>
                  {details[stage]}
                </pre>
              ) : (
                <span>{details[stage]}</span>
              )}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}
