'use client';

import React from 'react';
import { useAuth } from '@/context/AuthContext';
import { SessionSummary } from '@/types/chat';
import {
  MessageSquare,
  Plus,
  Trash2,
  LogOut,
  Shield,
  User as UserIcon,
  Clock,
  Sparkles,
} from 'lucide-react';

interface SessionControlsProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onDeleteSession: (sessionId: string) => void;
  isLoadingSessions?: boolean;
}

export default function SessionControls({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  isLoadingSessions = false,
}: SessionControlsProps) {
  const { user, logout } = useAuth();

  const formatTimestamp = (dateStr?: string) => {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  };

  return (
    <aside className="w-72 h-full flex flex-col glass-panel border-r border-gray-800 bg-gray-950/70 select-none">
      {/* Brand header */}
      <div className="p-4 border-b border-gray-800/80 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-white tracking-tight">KB Chatbot</h1>
            <p className="text-[11px] text-gray-400">Strict RAG Engine</p>
          </div>
        </div>
      </div>

      {/* New chat action */}
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="w-full py-2.5 px-3 rounded-xl bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border border-emerald-500/30 hover:border-emerald-500/50 text-xs font-semibold flex items-center justify-center gap-2 transition-all duration-200 shadow-sm group"
        >
          <Plus className="w-4 h-4 group-hover:scale-110 transition-transform" />
          <span>New Chat</span>
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        <div className="px-2 py-1 text-[11px] font-semibold text-gray-500 uppercase tracking-wider flex items-center justify-between">
          <span>Recent Sessions</span>
          {isLoadingSessions && <span className="text-[10px] lowercase animate-pulse text-gray-500">loading...</span>}
        </div>

        {sessions.length === 0 && !isLoadingSessions ? (
          <div className="px-3 py-8 text-center text-xs text-gray-500">
            No previous sessions. Start a conversation!
          </div>
        ) : (
          sessions.map((sess) => {
            const isActive = activeSessionId === sess.session_id;
            return (
              <div
                key={sess.session_id}
                onClick={() => onSelectSession(sess.session_id)}
                className={`group flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer text-xs transition-all duration-150 ${
                  isActive
                    ? 'bg-emerald-500/15 text-white border border-emerald-500/30 font-medium'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-900/60 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <MessageSquare
                    className={`w-3.5 h-3.5 flex-shrink-0 ${
                      isActive ? 'text-emerald-400' : 'text-gray-500'
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs">
                      {sess.snippet || `Session ${sess.session_id.slice(0, 8)}`}
                    </p>
                    <div className="flex items-center gap-2 text-[10px] text-gray-500">
                      <span>{sess.message_count} msgs</span>
                      {sess.last_message_at && (
                        <>
                          <span>•</span>
                          <span className="flex items-center gap-0.5">
                            <Clock className="w-2.5 h-2.5" />
                            {formatTimestamp(sess.last_message_at)}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(sess.session_id);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-all ml-1"
                  title="Delete Session"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Admin Portal quick link */}
      {user?.role === 'admin' && (
        <div className="px-3 pb-2">
          <a
            href="/admin"
            className="w-full py-2 px-3 rounded-xl bg-gray-900 hover:bg-gray-800 text-gray-300 hover:text-white border border-gray-800 hover:border-emerald-500/30 text-xs font-semibold flex items-center justify-between transition-all group"
          >
            <div className="flex items-center gap-2">
              <Shield className="w-3.5 h-3.5 text-emerald-400" />
              <span>Admin Portal</span>
            </div>
            <span className="text-[10px] text-gray-500 group-hover:text-emerald-400">→</span>
          </a>
        </div>
      )}

      {/* User profile & logout footer */}
      {user && (
        <div className="p-3 border-t border-gray-800/80 bg-gray-950/60">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5 min-w-0 flex-1">
              <div className="w-8 h-8 rounded-lg bg-gray-800 flex items-center justify-center text-gray-300 flex-shrink-0 border border-gray-700">
                {user.role === 'admin' ? (
                  <Shield className="w-4 h-4 text-emerald-400" />
                ) : (
                  <UserIcon className="w-4 h-4 text-gray-400" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-white truncate" title={user.email}>
                  {user.email}
                </p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span
                    className={`inline-block px-1.5 py-0.2 rounded text-[10px] font-semibold uppercase tracking-wider ${
                      user.role === 'admin'
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : 'bg-gray-800 text-gray-400 border border-gray-700'
                    }`}
                  >
                    {user.role}
                  </span>
                </div>
              </div>
            </div>

            <button
              onClick={logout}
              className="p-2 rounded-lg text-gray-400 hover:text-red-300 hover:bg-red-500/10 transition-colors"
              title="Sign Out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}
