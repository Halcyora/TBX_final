import React, { useState, useRef, useEffect } from 'react';
import { ChatMessage, FinanceAnswer } from '../lib/types';
import ResultsPanel from './ResultsPanel';
import StepsList from './StepsList';
import styles from '../styles/ChatInterface.module.css';

interface ChatInterfaceProps {
  messages: ChatMessage[];
  onSendMessage: (message: string) => void;
  loading: boolean;
  sessionId: string | null;
}

type TabId = 'chat' | 'results' | 'steps';

export default function ChatInterface({
  messages,
  onSendMessage,
  loading,
  sessionId,
}: ChatInterfaceProps) {
  const [input, setInput] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [ghostText, setGhostText] = useState<string>('');
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState<number>(-1);
  const [showDropdown, setShowDropdown] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<TabId>('chat');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Extract all results and steps from messages
  const allResults = messages
    .filter((msg) => msg.role === 'assistant' && msg.result)
    .map((msg) => msg.result as FinanceAnswer);

  const allSteps = messages
    .flatMap((msg, msgIdx) => {
      if (msg.result && msg.result.processing_stages) {
        return msg.result.processing_stages.map((stage, stageIdx) => ({
          stage,
          detail: msg.result?.stage_details?.[stage],
          msgIdx,
          stageIdx,
        }));
      }
      return [];
    });

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Debounced autocomplete search against Amazon Nova Micro endpoint
  useEffect(() => {
    if (input.trim().length < 2) {
      setSuggestions([]);
      setGhostText('');
      setShowDropdown(false);
      setActiveSuggestionIndex(-1);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
        const res = await fetch(`${apiUrl}/api/autocomplete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: input }),
        });
        if (res.ok) {
          const data = await res.json();
          const items: string[] = data.suggestions || [];
          setSuggestions(items);
          setShowDropdown(items.length > 0);
          setActiveSuggestionIndex(-1);

          // Inline Ghost Text calculation
          if (items.length > 0 && items[0].toLowerCase().startsWith(input.toLowerCase())) {
            setGhostText(items[0]);
          } else {
            setGhostText('');
          }
        }
      } catch (err) {
        console.error('Autocomplete fetch error:', err);
      }
    }, 180);

    return () => clearTimeout(timer);
  }, [input]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    // 1. Accept Inline Ghost Text on Tab or ArrowRight (at end of cursor)
    if ((e.key === 'Tab' || e.key === 'ArrowRight') && ghostText) {
      const target = e.currentTarget;
      if (target.selectionStart === input.length) {
        e.preventDefault();
        setInput(ghostText);
        setGhostText('');
        setShowDropdown(false);
        setSuggestions([]);
        return;
      }
    }

    if (!showDropdown || suggestions.length === 0) return;

    // 2. Keyboard Navigation in Dropdown Menu
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const nextIdx = (activeSuggestionIndex + 1) % suggestions.length;
      setActiveSuggestionIndex(nextIdx);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prevIdx = (activeSuggestionIndex - 1 + suggestions.length) % suggestions.length;
      setActiveSuggestionIndex(prevIdx);
    } else if (e.key === 'Enter' && activeSuggestionIndex >= 0) {
      e.preventDefault();
      const chosen = suggestions[activeSuggestionIndex];
      setInput(chosen);
      setShowDropdown(false);
      setSuggestions([]);
      setGhostText('');
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
    }
  };

  const handleSelectSuggestion = (suggestion: string) => {
    setInput(suggestion);
    setShowDropdown(false);
    setSuggestions([]);
    setGhostText('');
    inputRef.current?.focus();
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !loading && sessionId) {
      setShowDropdown(false);
      setSuggestions([]);
      setGhostText('');
      onSendMessage(input);
      setInput('');
    }
  };

  return (
    <div className={styles.chatContainer}>
      {/* Tab Bar */}
      <div className={styles.tabBar}>
        <button
          className={`${styles.tabButton} ${activeTab === 'chat' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          💬 Chat
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'results' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('results')}
        >
          📊 Results {allResults.length > 0 && `(${allResults.length})`}
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'steps' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('steps')}
          title="This tab can be hidden when sharing with users"
        >
          🔄 Steps {allSteps.length > 0 && `(${allSteps.length})`}
        </button>
      </div>

      {/* Chat Tab */}
      {activeTab === 'chat' && (
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
                className={`${styles.messageRow} ${styles[msg.role]}`}
              >
                <div className={styles.messageInner}>
                  <div className={styles.avatar}>
                    {msg.role === 'user' ? '🧑' : '🤖'}
                  </div>
                  <div className={styles.content}>
                    <p>{msg.content}</p>
                    {msg.result && <ResultsPanel result={msg.result} />}
                  </div>
                </div>
              </div>
            ))
          )}
          {loading && (
            <div className={`${styles.messageRow} ${styles.assistant}`}>
              <div className={styles.messageInner}>
                <div className={styles.avatar}>🤖</div>
                <div className={styles.content}>
                  <div className={styles.loading}>
                    <span></span><span></span><span></span>
                  </div>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      )}

      {/* Results Tab */}
      {activeTab === 'results' && (
        <div className={styles.tabContent}>
          {allResults.length === 0 ? (
            <div className={styles.emptyState}>
              <p>No results yet. Ask a question in the Chat tab to get started.</p>
            </div>
          ) : (
            <div className={styles.resultsList}>
              {allResults.map((result, idx) => (
                <div key={idx} className={styles.resultItem}>
                  <h3>Result #{idx + 1}</h3>
                  <ResultsPanel result={result} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Steps Tab */}
      {activeTab === 'steps' && (
        <div className={styles.tabContent}>
          {allSteps.length === 0 ? (
            <div className={styles.emptyState}>
              <p>No processing steps yet. Ask a question to see the pipeline steps.</p>
            </div>
          ) : (
            <div className={styles.stepsList}>
              {allSteps.map((step, idx) => (
                <div key={idx} className={styles.stepItemContainer}>
                  <div className={styles.stepMsgIndex}>Message #{step.msgIdx + 1}</div>
                  <div className={styles.stepDetail}>
                    <span className={styles.stepCheck}>✓</span>
                    <strong>{step.stage.replace(/_/g, ' ')}</strong>
                    {step.detail && <span className={styles.stepDescription}>{step.detail}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <form onSubmit={handleSubmit} className={styles.inputForm}>
        <div className={styles.inputBarWrapper} ref={containerRef}>
          {showDropdown && suggestions.length > 0 && (
            <ul className={styles.suggestionDropdown}>
              <li className={styles.suggestionHeader}>
                <span>Suggested Questions</span>
                <span className={styles.modelBadge}>⚡ Amazon Nova Micro</span>
              </li>
              {suggestions.map((item, idx) => (
                <li
                  key={idx}
                  className={`${styles.suggestionItem} ${idx === activeSuggestionIndex ? styles.active : ''}`}
                  onClick={() => handleSelectSuggestion(item)}
                >
                  <span className={styles.suggestionIcon}>🔍</span>
                  <span>{item}</span>
                  {idx === 0 && <span className={styles.tabHint}>Press Tab ↹</span>}
                </li>
              ))}
            </ul>
          )}

          <div className={styles.inputBar}>
            <div className={styles.inputWrapper}>
              {ghostText && ghostText.toLowerCase().startsWith(input.toLowerCase()) && (
                <div className={styles.ghostText}>
                  <span style={{ opacity: 0 }}>{input}</span>
                  <span>{ghostText.slice(input.length)}</span>
                </div>
              )}
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about your finances... (type to see suggestions)"
                disabled={loading || !sessionId}
                className={styles.input}
              />
            </div>
            <button
              type="submit"
              disabled={loading || !sessionId || !input.trim()}
              className={styles.sendButton}
            >
              ➤
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
