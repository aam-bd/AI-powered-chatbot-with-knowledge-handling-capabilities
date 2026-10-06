import { TokenResponse, User, SessionSummary } from '@/types/chat';

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
  return data.sessions || [];
}

export async function deleteChatSession(sessionId: string): Promise<boolean> {
  const res = await fetchWithAuth(`/chat/sessions/${sessionId}`, {
    method: 'DELETE',
  });
  return res.ok;
}
