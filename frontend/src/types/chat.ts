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
  id: string;
  session_id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChatMessageItem {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  kind?: MessageKind;
  citations?: CitationItem[];
  fallback_layer?: number | null;
  created_at: string;
}

export type ChatStreamEvent =
  | { type: 'token'; text: string }
  | { type: 'citations'; citations: CitationItem[] }
  | { type: 'retract'; text: string; reason?: string }
  | { type: 'error'; code: string; message: string }
  | { type: 'done'; session_id?: string; intent?: string; fallback_layer?: number | null };

export type DocumentStatus =
  | 'pending'
  | 'processing'
  | 'active'
  | 'updating'
  | 'deleting'
  | 'failed';

export interface DocumentItem {
  id: string;
  name: string;
  source_type: string;
  source_uri: string;
  sha256: string;
  size_bytes: number;
  status: DocumentStatus;
  active_version?: number | null;
  pending_version?: number | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

