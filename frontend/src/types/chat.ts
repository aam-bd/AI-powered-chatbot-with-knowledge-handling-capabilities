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

export interface LLMProvider {
  id: string;
  name: string;
  provider_type: string;
  base_url: string;
  has_key?: boolean;
  key_hint?: string | null;
  has_api_key?: boolean;
  api_key_masked_hint?: string | null;
  models?: string[];
  default_model: string;
  is_enabled?: boolean;
  is_active?: boolean;
  is_fallback?: boolean;
  created_at: string;
  updated_at: string;
  last_test_status?: 'success' | 'failed' | null;
  last_test_at?: string | null;
  last_tested_at?: string | null;
  last_test_latency_ms?: number | null;
  last_test_error?: string | null;
}

export interface LLMSettings {
  active_provider_id: string;
  active_model?: string;
  fallback_provider_id: string | null;
  fallback_model?: string | null;
  temperature: number;
  max_tokens: number;
  timeout_seconds?: number;
  version?: number;
}

export interface LLMProviderCreateInput {
  name: string;
  provider_type: string;
  base_url: string;
  api_key?: string;
  models: string[];
  default_model: string;
  is_enabled?: boolean;
}

export interface LLMProviderUpdateInput {
  name?: string;
  base_url?: string;
  api_key?: string;
  clear_api_key?: boolean;
  models?: string[];
  default_model?: string;
  is_enabled?: boolean;
}

export interface LLMTestResult {
  success: boolean;
  status: string;
  message: string;
  sanitized_error?: string | null;
}

export interface LLMModelsResult {
  provider_id: string;
  models: string[];
  source?: 'provider' | 'stored';
  cached?: boolean;
}

export interface HealthInfo {
  status: string;
  postgres?: string;
  redis?: string;
  qdrant?: string;
  llm_configured?: boolean;
  llm_provider?: string;
  llm_model?: string;
  embedding_model?: string;
  embedding_status?: string;
  reranker_model?: string;
  reranker_status?: string;
  version?: string;
}


