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
  is_preset?: boolean;
  preset_key?: string | null;
  docs_url?: string | null;
  key_required?: boolean;
  discovery_kind?: string;
  discovered_at?: string | null;
  discovered_count?: number;
}

export interface ProviderModel {
  id: string;
  provider_id: string;
  model_id: string;
  display_name?: string | null;
  context_length?: number | null;
  max_output_tokens?: number | null;
  price_prompt_per_1m?: number | null;
  price_completion_per_1m?: number | null;
  source: 'discovered' | 'manual';
  is_available: boolean;
  is_enabled: boolean;
  discovered_at: string;
}

export interface DiscoveredModel {
  model_id: string;
  display_name?: string | null;
  context_length?: number | null;
  max_output_tokens?: number | null;
  price_prompt_per_1m?: number | null;
  price_completion_per_1m?: number | null;
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
  preset_key?: string;
  discovery_kind?: string;
}

export interface LLMProviderUpdateInput {
  name?: string;
  base_url?: string;
  api_key?: string;
  clear_api_key?: boolean;
  models?: string[];
  default_model?: string;
  is_enabled?: boolean;
  discovery_kind?: string;
}

export interface ManualModelInput {
  model_id: string;
  display_name?: string;
  context_length?: number;
  max_output_tokens?: number;
  price_prompt_per_1m?: number;
  price_completion_per_1m?: number;
}

export interface DiscoverUnsavedInput {
  provider_type: string;
  base_url: string;
  api_key?: string;
  discovery_kind: string;
}

export interface LLMUsageSummaryItem {
  provider_id?: string | null;
  provider_name?: string | null;
  model_id: string;
  total_requests: number;
  total_prompt_tokens?: number | null;
  total_completion_tokens?: number | null;
  total_tokens?: number | null;
  total_errors: number;
  avg_latency_ms: number;
  estimated_cost?: number | null;
  cost_reason?: string | null;
}

export interface LLMUsageResponse {
  range: string;
  total_requests: number;
  total_prompt_tokens?: number | null;
  total_completion_tokens?: number | null;
  total_tokens?: number | null;
  total_errors: number;
  avg_latency_ms: number;
  total_estimated_cost?: number | null;
  items: LLMUsageSummaryItem[];
}

export interface LLMTestResult {
  success: boolean;
  status: string;
  message: string;
  sanitized_error?: string | null;
  discovered_count?: number | null;
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

// Prompt 7e-3: Admin System Overview & Control
export interface DependencyHealthItem {
  name: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  latency_ms?: number | null;
  message?: string | null;
  metadata?: Record<string, any> | null;
}

export interface AdminSystemHealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  version: string;
  checked_at: string;
  dependencies: Record<string, DependencyHealthItem>;
}

export interface RouteInfoItem {
  method: string;
  path: string;
  tags: string[];
  summary?: string | null;
  auth_level: 'admin' | 'user' | 'public';
}

export interface SystemRoutesResponse {
  base_url: string;
  docs_url: string;
  redoc_url: string;
  openapi_url: string;
  health_url: string;
  routes: RouteInfoItem[];
}

export interface VectorStoreStatsResponse {
  collection_name: string;
  status: string;
  points_count: number;
  vectors_count: number;
  segments_count: number;
  disk_data_size_bytes?: number | null;
  dense_dim: number;
  has_sparse: boolean;
  indexed_documents_count: number;
  active_versions_count: number;
  superseded_versions_count: number;
}

export interface ArchitectureOverviewResponse {
  dense_model: string;
  dense_dim: number;
  sparse_model: string;
  fusion_method: string;
  rrf_k: number;
  retrieval_top_k: number;
  reranker_model: string;
  reranker_threshold: number;
  rerank_top_n: number;
  chunk_size: number;
  chunk_overlap: number;
  history_window: number;
  guardrail_layers: string[];
  fallback_message: string;
}

export interface WorkerStatsResponse {
  online_workers_count: number;
  worker_names: string[];
  active_tasks_count: number;
  queue_length: number;
  last_beat_run?: string | null;
  last_reconciler_run?: string | null;
  reconciler_fixed_count: number;
  reconciler_last_status?: string | null;
  failed_ingestions_count: number;
}

export interface ChatQualityIndicatorsResponse {
  window: '24h' | '7d';
  total_queries: number;
  fallback_count: number;
  fallback_rate: number;
  layer1_fallback_count: number;
  layer2_fallback_count: number;
  layer3_fallback_count: number;
  avg_retrieval_score?: number | null;
  queries_with_no_sources: number;
}

export interface AuditLogEntryResponse {
  id: string;
  created_at: string;
  user_id?: string | null;
  user_email?: string | null;
  action: string;
  target_type?: string | null;
  target_id?: string | null;
  details?: Record<string, any> | null;
}

export interface RecentActivityResponse {
  audit_logs: AuditLogEntryResponse[];
  recent_errors: Array<Record<string, any>>;
}

export interface SystemSettingsResponse {
  reranker_threshold: number;
  retrieval_top_k: number;
  rerank_top_n: number;
  history_messages: number;
  rate_limit_per_minute: number;
  rate_limit_login_per_minute: number;
  sse_keepalive_interval: number;
  max_upload_size_bytes: number;
  version: number;
  updated_at: string;
}

export interface SystemSettingsUpdate {
  reranker_threshold?: number;
  retrieval_top_k?: number;
  rerank_top_n?: number;
  history_messages?: number;
  rate_limit_per_minute?: number;
  rate_limit_login_per_minute?: number;
  sse_keepalive_interval?: number;
  max_upload_size_bytes?: number;
}

export interface EnvironmentSettingItem {
  key: string;
  value: string;
  description?: string | null;
}

export interface SystemEnvironmentResponse {
  settings: EnvironmentSettingItem[];
}


