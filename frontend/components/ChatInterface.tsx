import React, { useState, useRef, useEffect } from 'react';
import { ChatMessage } from '../lib/types';
import styles from '../styles/ChatInterface.module.css';

interface ChatInterfaceProps {
  messages: ChatMessage[];
  onSendMessage: (message: string) => void;
  loading: boolean;
  sessionId: string | null;
}

export default function ChatInterface({
  messages,
  onSendMessage,
  loading,
  sessionId,
}: ChatInterfaceProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !loading && sessionId) {
      onSendMessage(input);
      setInput('');
    }
  };

  return (
    <div className={styles.chatContainer}>
      <div className={styles.messagesContainer}>
        {messages.length === 0 ? (
          <div className={styles.welcome}>
            <h2>Welcome to TBX Finance Assistant</h2>
            <p>Ask questions about your financial data. Examples:</p>
            <ul>
              <li>What's our total spend with vendor ID 123?</li>
              <li>Show me unreconciled transactions in Q3</li>
              <li>Which vendors have unusual payment patterns?</li>
              <li>List top 10 vendors by amount</li>
            </ul>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div
              key={idx}
              className={`${styles.message} ${styles[msg.role]}`}
            >
              <div className={styles.avatar}>
                {msg.role === 'user' ? '👤' : '🤖'}
              </div>
              <div className={styles.content}>
                <p>{msg.content}</p>
              </div>
            </div>
          ))
        )}
        {loading && (
          <div className={`${styles.message} ${styles.assistant}`}>
            <div className={styles.avatar}>🤖</div>
            <div className={styles.content}>
              <div className={styles.loading}>
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSubmit} className={styles.inputForm}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your finances..."
          disabled={loading || !sessionId}
          className={styles.input}
        />
        <button
          type="submit"
          disabled={loading || !sessionId || !input.trim()}
          className={styles.sendButton}
        >
          {loading ? 'Sending...' : 'Send'}
        </button>
      </form>
    </div>
  );
}
