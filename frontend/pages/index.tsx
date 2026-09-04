import React, { useState, useEffect } from 'react';
import ChatInterface from '../components/ChatInterface';
import SessionManager from '../components/SessionManager';
import ResultsPanel from '../components/ResultsPanel';
import { ChatMessage, FinanceAnswer } from '../lib/types';
import styles from '../styles/Home.module.css';

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [lastResult, setLastResult] = useState<FinanceAnswer | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Create session on mount
    const createSession = async () => {
      try {
        const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions/create`, {
          method: 'POST',
        });
        const data = await response.json();
        setSessionId(data.session_id);
      } catch (error) {
        console.error('Failed to create session:', error);
      }
    };
    createSession();
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
          model: 'qwen-7b', // Can be made selectable
        }),
      });

      const data = await response.json();
      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: data.message,
      };
      
      setMessages((prev) => [...prev, assistantMessage]);
      setLastResult(data);
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
    <div className={styles.container}>
      <header className={styles.header}>
        <h1>🏦 TBX Finance Assistant</h1>
        <p>Conversational AI for financial insights</p>
      </header>

      <div className={styles.mainLayout}>
        <div className={styles.chatPanel}>
          {sessionId && (
            <SessionManager
              sessionId={sessionId}
              messageCount={messages.length}
            />
          )}
          <ChatInterface
            messages={messages}
            onSendMessage={handleSendMessage}
            loading={loading}
            sessionId={sessionId}
          />
        </div>

        {lastResult && (
          <div className={styles.resultsPanel}>
            <ResultsPanel result={lastResult} />
          </div>
        )}
      </div>
    </div>
  );
}
