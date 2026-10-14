import {
  TokenResponse,
  User,
  UserRole,
  SessionSummary,
  ChatMessageItem,
  DocumentItem,
  LLMProvider,
  LLMSettings,
  LLMProviderCreateInput,
  LLMProviderUpdateInput,
  LLMTestResult,
  LLMModelsResult,
  HealthInfo,
  ProviderModel,
  DiscoveredModel,
  ManualModelInput,
  DiscoverUnsavedInput,
  LLMUsageResponse,
  AdminSystemHealthResponse,
  SystemRoutesResponse,
  VectorStoreStatsResponse,
  ArchitectureOverviewResponse,
  WorkerStatsResponse,
  ChatQualityIndicatorsResponse,
  RecentActivityResponse,
  SystemSettingsResponse,
  SystemSettingsUpdate,
  SystemEnvironmentResponse,
} from '@/types/chat';

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

const ACCESS_TOKEN_KEY = 'kb_chatbot_access_token';
const REFRESH_TOKEN_KEY = 'kb_chatbot_refresh_token';
const TOKEN_EXPIRY_KEY = 'kb_chatbot_token_expiry';

// In-memory token storage fallback for SSR
let memoryAccessToken: string | null = null;
let memoryRefreshToken: string | null = null;
let memoryTokenExpiry: number | null = null;

export function getAccessToken(): string | null {
  if (typeof window !== 'undefined') {
    return localStorage.getItem(ACCESS_TOKEN_KEY) || memoryAccessToken;
  }
  return memoryAccessToken;
}

export function getRefreshToken(): string | null {
  if (typeof window !== 'undefined') {
    return localStorage.getItem(REFRESH_TOKEN_KEY) || memoryRefreshToken;
  }
  return memoryRefreshToken;
}

export function setTokens(tokens: TokenResponse): void {
  const expiryTimestamp = Date.now() + (tokens.expires_in - 60) * 1000; // Refresh 60s before expiry
  memoryAccessToken = tokens.access_token;
  memoryRefreshToken = tokens.refresh_token;
  memoryTokenExpiry = expiryTimestamp;

  if (typeof window !== 'undefined') {
    localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
    localStorage.setItem(TOKEN_EXPIRY_KEY, expiryTimestamp.toString());
  }
}

export function clearTokens(): void {
  memoryAccessToken = null;
  memoryRefreshToken = null;
  memoryTokenExpiry = null;

  if (typeof window !== 'undefined') {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(TOKEN_EXPIRY_KEY);
  }
}

let isRefreshing = false;
let refreshPromise: Promise<string | null> | null = null;

/**
 * Refreshes access token using stored refresh token.
 * Prevents multiple simultaneous refresh calls via shared promise.
 */
export async function refreshAccessToken(): Promise<string | null> {
  const refreshTokenVal = getRefreshToken();
  if (!refreshTokenVal) {
    clearTokens();
    return null;
  }

  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }

  isRefreshing = true;
  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshTokenVal }),
      });

      if (!res.ok) {
        clearTokens();
        return null;
      }

      const data: TokenResponse = await res.json();
      setTokens(data);
      return data.access_token;
    } catch {
      clearTokens();
      return null;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/**
 * Authenticated fetch with automatic token refresh on 401 or impending expiration.
 */
export async function fetchWithAuth(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  let token = getAccessToken();

  // Check if token is nearing expiration
  let expiry = memoryTokenExpiry;
  if (!expiry && typeof window !== 'undefined') {
    const stored = localStorage.getItem(TOKEN_EXPIRY_KEY);
    if (stored) expiry = parseInt(stored, 10);
  }

  if (expiry && Date.now() > expiry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      token = refreshed;
    }
  }

  const headers = new Headers(options.headers || {});
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
  let response = await fetch(url, { ...options, headers });

  // If 401 Unauthorized, attempt immediate refresh and retry once
  if (response.status === 401 && getRefreshToken()) {
    const refreshedToken = await refreshAccessToken();
    if (refreshedToken) {
      headers.set('Authorization', `Bearer ${refreshedToken}`);
      response = await fetch(url, { ...options, headers });
    }
  }

  return response;
}

export async function registerUser(email: string, password: string): Promise<User> {
  const res = await fetch(`${API_BASE_URL}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Registration failed' }));
    throw new Error(err.detail || 'Registration failed');
  }

  return res.json();
}

export async function loginUser(email: string, password: string): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Login failed' }));
    throw new Error(err.detail || 'Invalid email or password');
  }

  const tokens: TokenResponse = await res.json();
  setTokens(tokens);
  return tokens;
}

export async function logoutUser(): Promise<void> {
  const refreshTokenVal = getRefreshToken();
  if (refreshTokenVal) {
    try {
      await fetch(`${API_BASE_URL}/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshTokenVal }),
      });
    } catch {
      // Ignore network errors on logout
    }
  }
  clearTokens();
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const res = await fetchWithAuth('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to update password' }));
    throw new Error(err.detail || 'Failed to update password');
  }
}

export async function getCurrentUser(): Promise<User> {
  const res = await fetchWithAuth('/auth/me');
  if (!res.ok) {
    throw new Error('Failed to fetch user profile');
  }
  return res.json();
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const res = await fetchWithAuth('/chat/sessions');
  if (!res.ok) {
    return [];
  }
  const data = await res.json();
  return Array.isArray(data) ? data : data.sessions || [];
}

export async function fetchSessionMessages(sessionId: string): Promise<ChatMessageItem[]> {
  const res = await fetchWithAuth(`/chat/sessions/${sessionId}/messages`);
  if (!res.ok) {
    throw new Error('Failed to fetch session messages');
  }
  return res.json();
}

export async function renameChatSession(sessionId: string, title: string): Promise<SessionSummary> {
  const res = await fetchWithAuth(`/chat/sessions/${sessionId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to rename session' }));
    throw new Error(err.detail || 'Failed to rename session');
  }
  return res.json();
}

export async function deleteChatSession(sessionId: string): Promise<boolean> {
  const res = await fetchWithAuth(`/chat/sessions/${sessionId}`, {
    method: 'DELETE',
  });
  return res.ok;
}

// -----------------------------------------------------------------------------
// Document Management Endpoints (Admin Only)
// -----------------------------------------------------------------------------

export async function fetchDocuments(
  skip = 0,
  limit = 50,
  statusFilter?: string
): Promise<DocumentItem[]> {
  const params = new URLSearchParams({
    skip: skip.toString(),
    limit: limit.toString(),
  });
  if (statusFilter) {
    params.set('status', statusFilter);
  }

  const res = await fetchWithAuth(`/documents?${params.toString()}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to fetch documents' }));
    throw new Error(err.detail || 'Failed to fetch documents');
  }
  return res.json();
}

export async function uploadDocumentFile(file: File): Promise<any> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetchWithAuth('/documents', {
    method: 'POST',
    body: formData,
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.message || 'File upload failed');
  }
  return data;
}

export async function uploadDocumentUrl(url: string, name?: string): Promise<any> {
  const res = await fetchWithAuth('/documents', {
    method: 'POST',
    body: JSON.stringify({ url, name }),
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.message || 'URL ingestion failed');
  }
  return data;
}

export async function updateDocumentFile(docId: string, file: File): Promise<any> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetchWithAuth(`/documents/${docId}`, {
    method: 'PUT',
    body: formData,
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.message || 'Document update failed');
  }
  return data;
}

export async function deleteDocument(docId: string): Promise<any> {
  const res = await fetchWithAuth(`/documents/${docId}`, {
    method: 'DELETE',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.message || 'Document deletion failed');
  }
  return data;
}

export async function getDocumentStatus(docId: string): Promise<any> {
  const res = await fetchWithAuth(`/documents/${docId}/status`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch document status');
  }
  return res.json();
}

/**
 * Fetches registered users for administrators.
 */
export async function fetchUsers(skip = 0, limit = 50): Promise<User[]> {
  const res = await fetchWithAuth(`/users?skip=${skip}&limit=${limit}`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch users');
  }
  return res.json();
}

/**
 * Updates a user's role or active status (admin only).
 */
export async function updateUser(
  userId: string,
  data: { role?: UserRole; is_active?: boolean }
): Promise<User> {
  const res = await fetchWithAuth(`/users/${userId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  });

  const resData = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(resData.detail || 'Failed to update user');
  }
  return resData;
}

/**
 * Fetches all LLM providers for the admin dashboard.
 */
export async function fetchLLMProviders(): Promise<LLMProvider[]> {
  const res = await fetchWithAuth('/admin/llm/providers');
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch LLM providers');
  }
  return res.json();
}

/**
 * Registers a new LLM provider.
 */
export async function createLLMProvider(payload: LLMProviderCreateInput): Promise<LLMProvider> {
  const res = await fetchWithAuth('/admin/llm/providers', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Failed to create LLM provider');
  }
  return data;
}

/**
 * Updates an existing LLM provider.
 */
export async function updateLLMProvider(
  providerId: string,
  payload: LLMProviderUpdateInput
): Promise<LLMProvider> {
  const res = await fetchWithAuth(`/admin/llm/providers/${providerId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Failed to update LLM provider');
  }
  return data;
}

/**
 * Deletes an LLM provider (refused if active or fallback).
 */
export async function deleteLLMProvider(providerId: string): Promise<void> {
  const res = await fetchWithAuth(`/admin/llm/providers/${providerId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const err: any = new Error(data.detail || 'Failed to delete LLM provider');
    err.status = res.status;
    throw err;
  }
}

/**
 * Tests connection to an LLM provider with short timeout.
 */
export async function testLLMProvider(providerId: string): Promise<LLMTestResult> {
  const res = await fetchWithAuth(`/admin/llm/providers/${providerId}/test`, {
    method: 'POST',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Connection test request failed');
  }
  return data;
}

/**
 * Lists available models from the provider or stored list.
 */
export async function fetchLLMModels(providerId: string): Promise<LLMModelsResult> {
  const res = await fetchWithAuth(`/admin/llm/models?provider_id=${providerId}`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch models');
  }
  return res.json();
}

/**
 * Fetches runtime LLM settings.
 */
export async function fetchLLMSettings(): Promise<LLMSettings> {
  const res = await fetchWithAuth('/admin/llm/settings');
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch LLM settings');
  }
  return res.json();
}

/**
 * Updates active and fallback runtime LLM settings.
 */
export async function updateLLMSettings(payload: Partial<LLMSettings>): Promise<LLMSettings> {
  const res = await fetchWithAuth('/admin/llm/settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Failed to update LLM settings');
  }
  return data;
}

/**
 * Fetches backend health status and read-only embedding/reranker model info.
 */
export async function fetchHealth(): Promise<HealthInfo> {
  const res = await fetch(`${API_BASE_URL}/health`);
  if (!res.ok) {
    throw new Error('Failed to fetch system health');
  }
  return res.json();
}

/**
 * Restores preset LLM providers that may have been missing or deleted.
 */
export async function restorePresetProviders(): Promise<LLMProvider[]> {
  const res = await fetchWithAuth('/admin/llm/providers/restore-presets', {
    method: 'POST',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Failed to restore preset providers');
  }
  return data;
}

/**
 * Triggers upstream model discovery for an existing provider and saves to catalog.
 */
export async function discoverProviderModels(providerId: string): Promise<ProviderModel[]> {
  const res = await fetchWithAuth(`/admin/llm/providers/${providerId}/discover`, {
    method: 'POST',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Model discovery failed');
  }
  return data;
}

/**
 * Probes discovery on unsaved credentials without persisting them.
 */
export async function discoverUnsavedModels(payload: DiscoverUnsavedInput): Promise<DiscoveredModel[]> {
  const res = await fetchWithAuth('/admin/llm/discover-unsaved', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Unsaved discovery probe failed');
  }
  return data;
}

/**
 * Retrieves the full model catalog for a provider.
 */
export async function fetchProviderCatalog(providerId: string): Promise<ProviderModel[]> {
  const res = await fetchWithAuth(`/admin/llm/providers/${providerId}/models`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch provider model catalog');
  }
  return res.json();
}

/**
 * Updates model enablement or overrides price per 1M tokens.
 */
export async function updateProviderModel(
  providerId: string,
  modelId: string,
  payload: { is_enabled?: boolean; price_prompt_per_1m?: number | null; price_completion_per_1m?: number | null }
): Promise<ProviderModel> {
  const res = await fetchWithAuth(`/admin/llm/providers/${providerId}/models/${encodeURIComponent(modelId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Failed to update model settings');
  }
  return data;
}

/**
 * Manually registers a model when auto-discovery fails.
 */
export async function addManualModel(providerId: string, payload: ManualModelInput): Promise<ProviderModel> {
  const res = await fetchWithAuth(`/admin/llm/providers/${providerId}/models/manual`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Failed to add manual model');
  }
  return data;
}

/**
 * Fetches aggregated LLM usage and estimated cost metrics.
 */
export async function fetchLLMUsage(range: '24h' | '7d' | '30d' = '24h'): Promise<LLMUsageResponse> {
  const res = await fetchWithAuth(`/admin/llm/usage?range=${range}`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch LLM usage metrics');
  }
  return res.json();
}

/**
 * Prompt 7e-3: Admin System Overview & Settings APIs
 */
export async function fetchSystemHealth(): Promise<AdminSystemHealthResponse> {
  const res = await fetchWithAuth('/admin/system/health');
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch system health');
  }
  return res.json();
}

export async function fetchSystemRoutes(): Promise<SystemRoutesResponse> {
  const res = await fetchWithAuth('/admin/system/routes');
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to introspect API routes');
  }
  return res.json();
}

export async function fetchVectorStoreStats(): Promise<VectorStoreStatsResponse> {
  const res = await fetchWithAuth('/admin/system/vector-store');
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch vector store stats');
  }
  return res.json();
}

export async function fetchArchitectureOverview(): Promise<ArchitectureOverviewResponse> {
  const res = await fetchWithAuth('/admin/system/architecture');
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch architecture overview');
  }
  return res.json();
}

export async function fetchWorkerStats(): Promise<WorkerStatsResponse> {
  const res = await fetchWithAuth('/admin/system/workers');
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch worker statistics');
  }
  return res.json();
}

export async function fetchChatQualityIndicators(window: '24h' | '7d' = '24h'): Promise<ChatQualityIndicatorsResponse> {
  const res = await fetchWithAuth(`/admin/system/quality?window=${window}`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch quality indicators');
  }
  return res.json();
}

export async function fetchRecentActivity(): Promise<RecentActivityResponse> {
  const res = await fetchWithAuth('/admin/system/activity');
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch recent audit activity');
  }
  return res.json();
}

export async function fetchSystemSettings(): Promise<SystemSettingsResponse> {
  const res = await fetchWithAuth('/admin/system/settings');
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch system settings');
  }
  return res.json();
}

export async function updateSystemSettings(payload: SystemSettingsUpdate): Promise<SystemSettingsResponse> {
  const res = await fetchWithAuth('/admin/system/settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Failed to update system settings');
  }
  return data;
}

export async function resetSystemSettings(): Promise<SystemSettingsResponse> {
  const res = await fetchWithAuth('/admin/system/settings/reset', {
    method: 'POST',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || 'Failed to reset system settings');
  }
  return data;
}

export async function fetchSystemEnvironment(): Promise<SystemEnvironmentResponse> {
  const res = await fetchWithAuth('/admin/system/environment');
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch environment configuration');
  }
  return res.json();
}




