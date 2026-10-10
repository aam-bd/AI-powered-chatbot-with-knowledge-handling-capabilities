import { ChatStreamEvent, CitationItem } from '@/types/chat';
import { API_BASE_URL, getAccessToken, refreshAccessToken } from './api';

export async function* streamChat(
  sessionId?: string | null,
  message?: string,
  initialToken?: string
): AsyncGenerator<ChatStreamEvent, void, unknown> {
  const userText = message || '';
  let token = initialToken || getAccessToken();

  if (!token) {
    yield {
      type: 'error',
      code: 'UNAUTHORIZED',
      message: 'You must be logged in to send messages.',
    };
    return;
  }

  const requestBody: { message: string; session_id?: string } = {
    message: userText,
  };
  if (sessionId) {
    requestBody.session_id = sessionId;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(requestBody),
    });
  } catch (err: any) {
    yield {
      type: 'error',
      code: 'NETWORK_ERROR',
      message: err.message || 'Network error communicating with chat server.',
    };
    return;
  }

  // Handle 401 token refresh retry
  if (response.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      token = refreshed;
      try {
        response = await fetch(`${API_BASE_URL}/chat/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(requestBody),
        });
      } catch (err: any) {
        yield {
          type: 'error',
          code: 'NETWORK_ERROR',
          message: err.message || 'Network error communicating with chat server.',
        };
        return;
      }
    }
  }

  if (!response.ok) {
    let errorDetail = 'Failed to initiate chat stream';
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || errJson.message || errorDetail;
    } catch {
      // fallback
    }
    yield {
      type: 'error',
      code: `HTTP_${response.status}`,
      message: errorDetail,
    };
    return;
  }

  if (!response.body) {
    yield {
      type: 'error',
      code: 'NO_RESPONSE_BODY',
      message: 'Server returned empty response stream.',
    };
    return;
  }

  const headerSessionId = response.headers.get('x-session-id') || response.headers.get('X-Session-ID');

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE blocks are delimited by two newlines
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || ''; // Keep incomplete block in buffer

      for (const block of blocks) {
        if (!block.trim()) continue;

        let currentEvent = 'message';
        let dataPayload = '';

        const lines = block.split('\n');
        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            dataPayload = line.slice(5).trim();
          }
        }

        if (!dataPayload) continue;

        try {
          const parsed = JSON.parse(dataPayload);

          switch (currentEvent) {
            case 'token':
              if (parsed.text) {
                yield { type: 'token', text: parsed.text };
              }
              break;

            case 'citations':
              yield {
                type: 'citations',
                citations: (parsed.citations || []) as CitationItem[],
              };
              break;

            case 'retract':
              yield {
                type: 'retract',
                text: parsed.replacement_text || parsed.text || "I'm sorry, I couldn't find information about that in my knowledge base.",
                reason: parsed.reason,
              };
              break;

            case 'error':
              yield {
                type: 'error',
                code: parsed.code || 'UNKNOWN_ERROR',
                message: parsed.detail || parsed.message || 'An error occurred during generation.',
              };
              break;

            case 'done':
              yield {
                type: 'done',
                session_id: parsed.session_id || headerSessionId || sessionId || undefined,
                intent: parsed.intent,
                fallback_layer: parsed.fallback_layer,
              };
              break;

            default:
              break;
          }
        } catch (jsonErr) {
          // If raw text or non-JSON data
          if (currentEvent === 'token') {
            yield { type: 'token', text: dataPayload };
          }
        }
      }
    }
  } catch (streamErr: any) {
    yield {
      type: 'error',
      code: 'STREAM_READ_ERROR',
      message: streamErr.message || 'Error reading stream from server.',
    };
  } finally {
    reader.releaseLock();
  }
}
