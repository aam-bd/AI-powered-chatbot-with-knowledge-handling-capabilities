'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import SessionControls from '@/components/SessionControls';
import ChatWindow from '@/components/ChatWindow';
import { SessionSummary } from '@/types/chat';
import { fetchSessions, deleteChatSession, renameChatSession } from '@/services/api';
import { Loader2 } from 'lucide-react';

export default function ChatPage() {
  const router = useRouter();
  const { user, isLoading: authLoading } = useAuth();

  const [sessionId, setSessionId] = useState<string>('');
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

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

  // Auth protection guard: wipes client chat state on logout
  useEffect(() => {
    if (!authLoading && !user) {
      setSessions([]);
      setSessionId('');
      router.push('/login');
    } else if (user) {
      loadSessions();
    }
  }, [user, authLoading, router, loadSessions]);

  const handleNewChat = () => {
    setSessionId('');
  };

  const handleSelectSession = (selectedId: string) => {
    setSessionId(selectedId);
  };

  const handleRenameSession = async (id: string, newTitle: string) => {
    try {
      await renameChatSession(id, newTitle);
      await loadSessions();
    } catch (err) {
      console.error('Failed to rename session', err);
    }
  };

  const handleDeleteSession = async (idToDelete: string) => {
    try {
      await deleteChatSession(idToDelete);
      if (idToDelete === sessionId) {
        setSessionId('');
      }
      await loadSessions();
    } catch (err) {
      console.error('Failed to delete session', err);
    }
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
    <div className="h-screen w-screen flex overflow-hidden bg-background relative">
      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden animate-fade-in"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar container with mobile slide-in */}
      <div
        className={`fixed inset-y-0 left-0 z-40 md:static md:z-auto transition-transform duration-200 ease-in-out ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        }`}
      >
        <SessionControls
          sessions={sessions}
          activeSessionId={sessionId}
          onSelectSession={(id) => {
            handleSelectSession(id);
            setSidebarOpen(false);
          }}
          onNewChat={() => {
            handleNewChat();
            setSidebarOpen(false);
          }}
          onRenameSession={handleRenameSession}
          onDeleteSession={handleDeleteSession}
          isLoadingSessions={isLoadingSessions}
        />
      </div>

      <main className="flex-1 h-full flex flex-col min-w-0">
        <ChatWindow
          key={sessionId || 'new-chat'}
          sessionId={sessionId}
          onSessionCreated={(newId) => {
            setSessionId(newId);
            loadSessions();
          }}
          onSessionUpdated={loadSessions}
          onNewChat={handleNewChat}
          onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
        />
      </main>
    </div>
  );
}
