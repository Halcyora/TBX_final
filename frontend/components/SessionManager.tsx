import React, { useState, useEffect } from 'react';
import styles from '../styles/SessionManager.module.css';

interface SessionManagerProps {
  sessionId: string;
  messageCount: number;
}

export default function SessionManager({
  sessionId,
  messageCount,
}: SessionManagerProps) {
  const [uptime, setUptime] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setUptime((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(sessionId);
    alert('Session ID copied to clipboard');
  };

  return (
    <div className={styles.container}>
      <div className={styles.item}>
        <code className={styles.value}>{sessionId.slice(0, 8)}...</code>
        <button onClick={copyToClipboard} className={styles.copyBtn} title="Copy session ID">
          📋
        </button>
      </div>
      <div className={styles.item}>
        <span className={styles.label}>{messageCount} msgs</span>
      </div>
      <div className={styles.item}>
        <span className={styles.label}>{formatTime(uptime)}</span>
      </div>
    </div>
  );
}
