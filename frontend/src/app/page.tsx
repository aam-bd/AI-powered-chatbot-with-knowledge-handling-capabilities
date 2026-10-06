'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import SessionControls from '@/components/SessionControls';
import ChatWindow from '@/components/ChatWindow';
import { SessionSummary } from '@/types/chat';
import { fetchSessions, deleteChatSession } from '@/services/api';
import { Loader2 } from 'lucide-react';

function generateSessionId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'sess-' + Math.random().toString(36).substring(2, 15);
}

export default function ChatPage() {
  const router = useRouter();
  const { user, isLoading: authLoading } = useAuth();

  const [sessionId, setSessionId] = useState<string>('');
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);

  // Initialize fresh session ID on mount
  useEffect(() => {
    setSessionId(generateSessionId());
  }, []);

  const loadSessions = useCallback(async () => {
    if (!user) return;
    setIsLoadingSessions(true);
    try {
      const data = await fetchSessions();
      setSessions(data);
    } catch {
      // ignore
    } finally {
      setIsLoadingSessions(false);
    }
  }, [user]);

  // Auth protection guard
  useEffect(() => {
    if (!authLoading && !user) {
      router.push('/login');
    } else if (user) {
      loadSessions();
    }
  }, [user, authLoading, router, loadSessions]);

  const handleNewChat = async () => {
    if (sessionId) {
      try {
        await deleteChatSession(sessionId);
      } catch {
        // session might not exist in redis yet, safe to proceed
      }
    }
    const newId = generateSessionId();
    setSessionId(newId);
    await loadSessions();
  };

  const handleSelectSession = (selectedId: string) => {
    setSessionId(selectedId);
  };

  const handleDeleteSession = async (idToDelete: string) => {
    await deleteChatSession(idToDelete);
    if (idToDelete === sessionId) {
      setSessionId(generateSessionId());
    }
    await loadSessions();
  };

  if (authLoading || (!user && typeof window !== 'undefined')) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-background text-emerald-400 gap-3">
        <Loader2 className="w-8 h-8 animate-spin" />
        <p className="text-xs text-gray-400">Loading session and authenticating...</p>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <div className="h-screen w-screen flex overflow-hidden bg-background">
      <SessionControls
        sessions={sessions}
        activeSessionId={sessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        isLoadingSessions={isLoadingSessions}
      />

      <main className="flex-1 h-full flex flex-col min-w-0">
        {sessionId && (
          <ChatWindow
            key={sessionId}
            sessionId={sessionId}
            onSessionUpdated={loadSessions}
            onNewChat={handleNewChat}
          />
        )}
      </main>
    </div>
  );
}
