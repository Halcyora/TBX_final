import React from 'react';
import { SessionInfo } from '../lib/types';
import styles from '../styles/Sidebar.module.css';

interface SidebarProps {
  sessions: SessionInfo[];
  activeSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onDeleteSession: (sessionId: string) => void;
  disabled?: boolean;
}

export default function Sidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  disabled,
}: SidebarProps) {
  return (
    <aside className={styles.sidebar}>
      <button className={styles.newChatBtn} onClick={onNewChat} disabled={disabled}>
        + New chat
      </button>
      <div className={styles.sessionList}>
        {sessions.length === 0 ? (
          <p className={styles.empty}>No conversations yet</p>
        ) : (
          sessions.map((session) => (
            <div
              key={session.session_id}
              className={`${styles.sessionRow} ${
                session.session_id === activeSessionId ? styles.active : ''
              }`}
            >
              <button
                className={styles.sessionItem}
                onClick={() => onSelectSession(session.session_id)}
                disabled={disabled}
                title={session.preview || 'New chat'}
              >
                <span className={styles.sessionPreview}>
                  {session.preview || 'New chat'}
                </span>
                <span className={styles.sessionMeta}>{session.messages_count} msgs</span>
              </button>
              <button
                className={styles.deleteBtn}
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm('Delete this conversation? This cannot be undone.')) {
                    onDeleteSession(session.session_id);
                  }
                }}
                disabled={disabled}
                title="Delete conversation"
              >
                🗑️
              </button>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
