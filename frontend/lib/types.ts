// Shared types for the TBX Finance Assistant frontend.
// Mirrors backend/main.py's ChatResponse/SessionInfo pydantic models exactly - keep in sync.
//
// This file previously never existed in git on either branch: .gitignore's Python-venv
// lib/ pattern also matched frontend/lib/, so it was silently excluded from every commit.
// Reconstructed from actual usage across ChatInterface.tsx/ResultsPanel.tsx/Sidebar.tsx/index.tsx.

export interface Anomaly {
  transaction_id: string;
  vendor_id?: string | null;
  amount?: number | null;
  reason: string;
  severity: 'high' | 'medium';
}

export interface GroundingInfo {
  sql_query: string;
  data_source: string;
  execution_time_ms?: number;
  rows_analyzed?: number;
  date_queried?: string;
  filters_applied?: Record<string, unknown>;
  anomalies_detected?: number;
}

// The full /chat response payload (backend/main.py's ChatResponse).
export interface FinanceAnswer {
  session_id: string;
  message: string;
  confidence_score: number;
  confidence_band: 'high' | 'medium' | 'low';
  grounding_info: GroundingInfo;
  anomalies_detected: Anomaly[];
  query_results: Record<string, unknown>[];
  processing_stages: string[];
  stage_details: Record<string, string>;
  export_available: boolean;
  export_filename?: string | null;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  result?: FinanceAnswer;
}

// Matches both the single-session GET (backend's SessionInfo model) and the /sessions list
// endpoint (which additionally includes `preview`, the first question asked in that session).
export interface SessionInfo {
  session_id: string;
  created_at: string;
  messages_count: number;
  last_message_at: string;
  preview?: string | null;
}
