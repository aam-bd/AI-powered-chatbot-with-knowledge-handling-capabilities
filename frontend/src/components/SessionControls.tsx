'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { SessionSummary } from '@/types/chat';
import AccessibilityTrigger from './AccessibilityTrigger';
import {
  MessageSquare,
  Plus,
  Trash2,
  LogOut,
  Shield,
  User as UserIcon,
  Clock,
  Sparkles,
  KeyRound,
  Edit2,
  Check,
  X,
} from 'lucide-react';

interface SessionControlsProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onRenameSession?: (sessionId: string, newTitle: string) => Promise<void> | void;
  onDeleteSession: (sessionId: string) => void;
  isLoadingSessions?: boolean;
}

export default function SessionControls({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onRenameSession,
  onDeleteSession,
  isLoadingSessions = false,
}: SessionControlsProps) {
  const { user, logout } = useAuth();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const formatTimestamp = (dateStr?: string) => {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  };

  const handleStartRename = (e: React.MouseEvent, sess: SessionSummary) => {
    e.stopPropagation();
    setEditingId(sess.session_id);
    setEditTitle(sess.title || '');
    setConfirmDeleteId(null);
  };

  const handleSaveRename = async (e?: React.MouseEvent | React.FormEvent, sessionId?: string) => {
    if (e) e.stopPropagation();
    const targetId = sessionId || editingId;
    if (!targetId || !editTitle.trim()) {
      setEditingId(null);
      return;
    }
    if (onRenameSession) {
      await onRenameSession(targetId, editTitle.trim());
    }
    setEditingId(null);
  };

  const handleCancelRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(null);
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
            <p className="text-xs text-slate-300 font-medium">Strict RAG Engine</p>
          </div>
        </div>
      </div>

      {/* New chat action */}
      <div className="p-3">
        <button
          onClick={onNewChat}
          aria-label="Start a new chat conversation"
          className="w-full py-2.5 px-3 rounded-xl bg-emerald-600/25 hover:bg-emerald-600/35 text-emerald-300 border border-emerald-500/30 hover:border-emerald-500/50 text-xs font-semibold flex items-center justify-center gap-2 transition-all duration-200 shadow-sm group"
        >
          <Plus className="w-4 h-4 group-hover:scale-110 transition-transform" />
          <span>New Chat</span>
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        <div className="px-2 py-1 text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
          <span>Conversations</span>
          {isLoadingSessions && <span className="text-xs lowercase animate-pulse text-slate-400">loading...</span>}
        </div>

        {sessions.length === 0 && !isLoadingSessions ? (
          <div className="px-3 py-8 text-center text-xs text-slate-400 font-medium">
            No previous sessions. Start a conversation!
          </div>
        ) : (
          sessions.map((sess) => {
            const isActive = activeSessionId === sess.session_id;
            const isEditing = editingId === sess.session_id;
            const isConfirmingDelete = confirmDeleteId === sess.session_id;

            return (
              <div
                key={sess.session_id}
                onClick={() => {
                  if (!isEditing && !isConfirmingDelete) {
                    onSelectSession(sess.session_id);
                  }
                }}
                className={`group relative flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer text-xs transition-all duration-150 ${
                  isActive
                    ? 'bg-emerald-500/15 text-white border border-emerald-500/30 font-semibold'
                    : 'text-slate-300 hover:text-white hover:bg-gray-900/70 border border-transparent'
                }`}
              >
                {isEditing ? (
                  <div
                    className="flex items-center gap-1.5 w-full"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleSaveRename(e, sess.session_id);
                        if (e.key === 'Escape') setEditingId(null);
                      }}
                      autoFocus
                      aria-label="Edit chat title"
                      className="flex-1 bg-gray-900 text-white text-xs px-2 py-1 rounded border border-emerald-500/50 focus:outline-none focus:ring-1 focus:ring-emerald-400"
                    />
                    <button
                      onClick={(e) => handleSaveRename(e, sess.session_id)}
                      className="p-1.5 rounded text-emerald-400 hover:bg-emerald-500/20"
                      title="Save"
                      aria-label="Save title"
                    >
                      <Check className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={handleCancelRename}
                      className="p-1.5 rounded text-slate-300 hover:text-white hover:bg-gray-800"
                      title="Cancel"
                      aria-label="Cancel editing"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ) : isConfirmingDelete ? (
                  <div
                    className="flex items-center justify-between w-full py-0.5 text-xs text-red-300"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <span className="text-xs font-semibold text-red-300">Delete chat?</span>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteSession(sess.session_id);
                          setConfirmDeleteId(null);
                        }}
                        className="px-2 py-1 rounded bg-red-600/30 hover:bg-red-600/50 text-red-200 text-xs font-semibold border border-red-500/40"
                      >
                        Delete
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDeleteId(null);
                        }}
                        className="px-2 py-1 rounded bg-gray-800 text-slate-300 hover:text-white text-xs"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <MessageSquare
                        className={`w-3.5 h-3.5 flex-shrink-0 ${
                          isActive ? 'text-emerald-400' : 'text-slate-400'
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium" title={sess.title}>
                          {sess.title || `Chat ${sess.session_id.slice(0, 8)}`}
                        </p>
                        <div className="flex items-center gap-2 text-xs text-slate-400 font-medium">
                          <span>{sess.message_count} msgs</span>
                          {sess.updated_at && (
                            <>
                              <span>•</span>
                              <span className="flex items-center gap-0.5">
                                <Clock className="w-3 h-3 text-slate-400" />
                                {formatTimestamp(sess.updated_at)}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      {onRenameSession && (
                        <button
                          type="button"
                          onClick={(e) => handleStartRename(e, sess)}
                          className="p-1.5 rounded text-slate-400 hover:text-emerald-300 hover:bg-emerald-500/15 transition-all"
                          title="Rename Chat"
                          aria-label="Rename Chat"
                        >
                          <Edit2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDeleteId(sess.session_id);
                        }}
                        className="p-1.5 rounded text-slate-400 hover:text-red-300 hover:bg-red-500/15 transition-all"
                        title="Delete Chat"
                        aria-label="Delete Chat"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Accessibility Preferences Trigger */}
      <div className="px-3 pb-2">
        <AccessibilityTrigger variant="sidebar" />
      </div>

      {/* Admin Portal quick link */}
      {user?.role === 'admin' && (
        <div className="px-3 pb-2">
          <a
            href="/admin"
            className="w-full py-2 px-3 rounded-xl bg-gray-900 hover:bg-gray-800 text-slate-200 hover:text-white border border-gray-800 hover:border-emerald-500/30 text-xs font-semibold flex items-center justify-between transition-all group"
          >
            <div className="flex items-center gap-2">
              <Shield className="w-3.5 h-3.5 text-emerald-400" />
              <span>Admin Portal</span>
            </div>
            <span className="text-xs text-slate-400 group-hover:text-emerald-300 font-bold">→</span>
          </a>
        </div>
      )}

      {/* User profile & logout footer */}
      {user && (
        <div className="p-3 border-t border-gray-800/80 bg-gray-950/60">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5 min-w-0 flex-1">
              <div className="w-8 h-8 rounded-lg bg-gray-800 flex items-center justify-center text-slate-200 flex-shrink-0 border border-gray-700">
                {user.role === 'admin' ? (
                  <Shield className="w-4 h-4 text-emerald-400" />
                ) : (
                  <UserIcon className="w-4 h-4 text-slate-300" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-white truncate" title={user.email}>
                  {user.email}
                </p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span
                    className={`inline-block px-1.5 py-0.5 rounded text-xs font-semibold uppercase tracking-wider ${
                      user.role === 'admin'
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : 'bg-gray-800 text-slate-300 border border-gray-700'
                    }`}
                  >
                    {user.role}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1">
              <Link
                href="/account"
                className="p-2 rounded-lg text-slate-300 hover:text-emerald-300 hover:bg-emerald-500/10 transition-colors"
                title="Account Settings & Password"
                aria-label="Account Settings & Password"
              >
                <KeyRound className="w-4 h-4" />
              </Link>
              <button
                onClick={logout}
                className="p-2 rounded-lg text-slate-300 hover:text-red-300 hover:bg-red-500/10 transition-colors"
                title="Sign Out"
                aria-label="Sign Out"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
