import React, { useState, useEffect, useCallback, useRef } from 'react';
import ChatInterface from '../components/ChatInterface';
import SessionManager from '../components/SessionManager';
import Sidebar from '../components/Sidebar';
import { ChatMessage, SessionInfo } from '../lib/types';
import styles from '../styles/Home.module.css';

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [entities, setEntities] = useState<string[]>([]);
  const [entityId, setEntityId] = useState<string>('');
  const didInitRef = useRef(false);

  useEffect(() => {
    const loadEntities = async () => {
      try {
        const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/entities`);
        if (response.ok) {
          setEntities(await response.json());
        }
      } catch (error) {
        console.error('Failed to list entities:', error);
      }
    };
    loadEntities();
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions`);
      if (response.ok) {
        setSessions(await response.json());
      }
    } catch (error) {
      console.error('Failed to list sessions:', error);
    }
  }, []);

  const createNewSession = useCallback(async () => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions/create`, {
        method: 'POST',
      });
      const data = await response.json();
      localStorage.setItem('tbx_session_id', data.session_id);
      setSessionId(data.session_id);
      setMessages([]);
      refreshSessions();
    } catch (error) {
      console.error('Failed to create session:', error);
    }
  }, [refreshSessions]);

  const switchToSession = useCallback(async (targetSessionId: string) => {
    localStorage.setItem('tbx_session_id', targetSessionId);
    setSessionId(targetSessionId);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions/${targetSessionId}/messages`);
      setMessages(response.ok ? await response.json() : []);
    } catch (error) {
      console.error('Failed to load session messages:', error);
      setMessages([]);
    }
  }, []);

  const deleteSession = useCallback(async (targetSessionId: string) => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions/${targetSessionId}`, {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error('Failed to delete session');

      const remaining = sessions.filter((s) => s.session_id !== targetSessionId);
      setSessions(remaining);

      // If the active session was deleted, switch to another existing one or start fresh
      if (targetSessionId === sessionId) {
        if (remaining.length > 0) {
          await switchToSession(remaining[0].session_id);
        } else {
          await createNewSession();
        }
      }
    } catch (error) {
      console.error('Failed to delete session:', error);
      alert('Failed to delete conversation. Please try again.');
    }
  }, [sessions, sessionId, switchToSession, createNewSession]);

  useEffect(() => {
    // Guard against React StrictMode's dev-only double effect invocation,
    // which would otherwise race two concurrent session creations
    if (didInitRef.current) return;
    didInitRef.current = true;

    // Reuse a still-valid session from a previous page load instead of always creating a new one
    const restoreOrCreateSession = async () => {
      try {
        // First, list all existing sessions to pick the most recent one
        const listResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions`);
        const existingSessions: SessionInfo[] = listResponse.ok ? await listResponse.json() : [];
        
        if (existingSessions.length > 0) {
          // Prefer the stored session if it's still valid
          const storedSessionId = localStorage.getItem('tbx_session_id');
          const validStoredSession = storedSessionId && existingSessions.some(s => s.session_id === storedSessionId);
          
          const targetSessionId = validStoredSession ? storedSessionId : existingSessions[0].session_id;
          await switchToSession(targetSessionId);
          setSessions(existingSessions);
          return;
        }
      } catch (error) {
        console.error('Failed to list existing sessions:', error);
      }

      // Only create a brand new session if truly none exist
      await createNewSession();
    };
    restoreOrCreateSession();
  }, [refreshSessions, switchToSession, createNewSession]);

  const handleSendMessage = async (message: string) => {
    if (!sessionId || !message.trim()) return;

    setLoading(true);
    const userMessage: ChatMessage = { role: 'user', content: message };
    setMessages((prev) => [...prev, userMessage]);

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message: userMessage,
          model: 'qwen-1.5b', // HuggingFace Qwen 1.5B
          entity_id: entityId || null,
        }),
      });

      const data = await response.json();
      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: data.message,
        result: data,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      refreshSessions();
    } catch (error) {
      console.error('Failed to send message:', error);
      const errorMessage: ChatMessage = {
        role: 'assistant',
        content: 'Error: Failed to process your query. Please try again.',
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.appLayout}>
      <Sidebar
        sessions={sessions}
        activeSessionId={sessionId}
        onSelectSession={switchToSession}
        onNewChat={createNewSession}
        onDeleteSession={deleteSession}
        disabled={loading}
      />
      <div className={styles.container}>
        <header className={styles.header}>
          <h1>🏦 TBX Finance Assistant</h1>
          {sessionId && (
            <SessionManager
              sessionId={sessionId}
              messageCount={messages.length}
            />
          )}
        </header>

        <div className={styles.chatPanel}>
          <ChatInterface
            messages={messages}
            onSendMessage={handleSendMessage}
            loading={loading}
            sessionId={sessionId}
            entities={entities}
            entityId={entityId}
            onEntityChange={setEntityId}
          />
        </div>
      </div>
    </div>
  );
}
