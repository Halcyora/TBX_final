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
  const didInitRef = useRef(false);

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

  useEffect(() => {
    // Guard against React StrictMode's dev-only double effect invocation,
    // which would otherwise race two concurrent session creations
    if (didInitRef.current) return;
    didInitRef.current = true;

    // Reuse a still-valid session from a previous page load instead of always creating a new one
    const restoreOrCreateSession = async () => {
      const storedSessionId = localStorage.getItem('tbx_session_id');

      if (storedSessionId) {
        try {
          const existing = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions/${storedSessionId}`);
          if (existing.ok) {
            await switchToSession(storedSessionId);
            refreshSessions();
            return;
          }
        } catch (error) {
          console.error('Failed to validate existing session:', error);
        }
      }

      // Stored session is gone (e.g. backend restarted) - fall back to the most recently
      // active existing session instead of silently spawning a new empty one. Only create
      // a brand new session if none exist at all; explicit new chats go through onNewChat.
      try {
        const listResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions`);
        const existingSessions: SessionInfo[] = listResponse.ok ? await listResponse.json() : [];
        if (existingSessions.length > 0) {
          await switchToSession(existingSessions[0].session_id);
          setSessions(existingSessions);
          return;
        }
      } catch (error) {
        console.error('Failed to list existing sessions:', error);
      }

      await createNewSession();
    };
    restoreOrCreateSession();
  }, []);

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
          model: 'amazon.nova-micro', // AWS Bedrock; can be made selectable
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
          />
        </div>
      </div>
    </div>
  );
}
