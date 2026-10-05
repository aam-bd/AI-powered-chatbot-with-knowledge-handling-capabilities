// Placeholder for streamChat SSE service (Phase 5)
export interface ChatStreamEvent {
  event: 'token' | 'citations' | 'retract' | 'error' | 'done';
  data: any;
}

export async function* streamChat(sessionId: string, message: string, token: string): AsyncGenerator<ChatStreamEvent> {
  // To be implemented in Phase 5
}
