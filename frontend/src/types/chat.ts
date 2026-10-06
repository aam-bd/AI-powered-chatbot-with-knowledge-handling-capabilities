export type UserRole = 'user' | 'admin';

export interface User {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at?: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface CitationItem {
  tag: string;
  document: string;
  page: number | null;
  section: string | null;
  chunk_id: string;
}

export type MessageKind = 'normal' | 'clarify' | 'fallback';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  kind?: MessageKind;
  citations?: CitationItem[];
  timestamp: string;
  isStreaming?: boolean;
  isRetracted?: boolean;
  isError?: boolean;
}

export interface SessionSummary {
  session_id: string;
  message_count: number;
  last_message_at: string;
  snippet: string;
}

export type ChatStreamEvent =
  | { type: 'token'; text: string }
  | { type: 'citations'; citations: CitationItem[] }
  | { type: 'retract'; text: string; reason?: string }
  | { type: 'error'; code: string; message: string }
  | { type: 'done'; intent?: string; fallback_layer?: number | null };
