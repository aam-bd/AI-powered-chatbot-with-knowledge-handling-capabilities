'use client';

import React, { useState, useRef, useEffect } from 'react';
import { ChatMessage, CitationItem } from '@/types/chat';
import { streamChat } from '@/services/streamChat';
import CitationsDrawer from './CitationsDrawer';
import {
  Send,
  Loader2,
  FileText,
  AlertCircle,
  Sparkles,
  Bot,
  User as UserIcon,
  RotateCcw,
  BookOpen,
  Menu,
} from 'lucide-react';

interface ChatWindowProps {
  sessionId: string;
  onSessionUpdated?: () => void;
  onNewChat?: () => void;
  onToggleSidebar?: () => void;
}

export default function ChatWindow({
  sessionId,
  onSessionUpdated,
  onNewChat,
  onToggleSidebar,
}: ChatWindowProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeCitations, setActiveCitations] = useState<CitationItem[]>([]);
  const [activeCitationTag, setActiveCitationTag] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Adjust textarea height automatically
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        140
      )}px`;
    }
  };

  const handleOpenDrawer = (citations: CitationItem[], tag?: string) => {
    setActiveCitations(citations);
    setActiveCitationTag(tag || null);
    setDrawerOpen(true);
  };

  const handleSendMessage = async (textToSend?: string) => {
    const text = (textToSend || inputValue).trim();
    if (!text || isStreaming) return;

    setErrorBanner(null);
    setInputValue('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }

    const userMsgId = `user-${Date.now()}`;
    const assistantMsgId = `assistant-${Date.now()}`;

    const userMessage: ChatMessage = {
      id: userMsgId,
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    };

    const initialAssistantMessage: ChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isStreaming: true,
      citations: [],
    };

    setMessages((prev) => [...prev, userMessage, initialAssistantMessage]);
    setIsStreaming(true);

    try {
      const eventGen = streamChat(sessionId, text);
      let accumulatedText = '';
      let currentCitations: CitationItem[] = [];

      for await (const event of eventGen) {
        if (event.type === 'token') {
          accumulatedText += event.text;
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMsgId
                ? { ...msg, content: accumulatedText }
                : msg
            )
          );
        } else if (event.type === 'citations') {
          currentCitations = event.citations;
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMsgId
                ? { ...msg, citations: currentCitations }
                : msg
            )
          );
        } else if (event.type === 'retract') {
          // Layer 3 Retract event: replace accumulated text with fallback and wipe citations
          accumulatedText = event.text;
          currentCitations = [];
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMsgId
                ? {
                    ...msg,
                    content: accumulatedText,
                    citations: [],
                    kind: 'fallback',
                    isRetracted: true,
                  }
                : msg
            )
          );
        } else if (event.type === 'error') {
          setErrorBanner(`${event.code}: ${event.message}`);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMsgId
                ? {
                    ...msg,
                    content:
                      accumulatedText ||
                      'Something went wrong on my side. Please try again.',
                    isError: true,
                  }
                : msg
            )
          );
        } else if (event.type === 'done') {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMsgId
                ? {
                    ...msg,
                    isStreaming: false,
                    content: accumulatedText,
                    citations: currentCitations,
                  }
                : msg
            )
          );
          if (onSessionUpdated) onSessionUpdated();
        }
      }
    } catch (err: any) {
      setErrorBanner(err.message || 'Stream connection interrupted');
    } finally {
      setIsStreaming(false);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId ? { ...msg, isStreaming: false } : msg
        )
      );
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Helper to render text with clickable [C1] badge links
  const renderMessageContent = (content: string, citations?: CitationItem[]) => {
    if (!content) return null;

    // Split on [C1], [C2], etc.
    const parts = content.split(/(\[C\d+\])/g);
    return (
      <div className="whitespace-pre-wrap leading-relaxed text-sm">
        {parts.map((part, i) => {
          const match = part.match(/^\[(C\d+)\]$/);
          if (match && citations && citations.length > 0) {
            const tag = match[1];
            const found = citations.find((c) => c.tag === tag);
            return (
              <button
                key={i}
                type="button"
                onClick={() => handleOpenDrawer(citations, tag)}
                className="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded text-[11px] font-semibold bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 transition-colors align-baseline"
                title={found ? `${found.document} (p. ${found.page ?? 'N/A'})` : `Citation ${tag}`}
              >
                [{tag}]
              </button>
            );
          }
          return <span key={i}>{part}</span>;
        })}
      </div>
    );
  };

  return (
    <div className="flex-1 h-full flex flex-col bg-background relative overflow-hidden">
      {/* Top Navbar */}
      <div className="h-14 px-4 sm:px-6 border-b border-gray-800 glass-panel flex items-center justify-between z-10">
        <div className="flex items-center gap-3">
          {onToggleSidebar && (
            <button
              onClick={onToggleSidebar}
              className="md:hidden p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
              title="Toggle Sessions Menu"
            >
              <Menu className="w-5 h-5" />
            </button>
          )}
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs font-medium text-gray-300">
            Session: <span className="font-mono text-emerald-400">{sessionId.slice(0, 8)}...</span>
          </span>
        </div>

        <div className="flex items-center gap-2">
          {onNewChat && (
            <button
              onClick={onNewChat}
              className="text-xs px-3 py-1.5 rounded-lg bg-gray-800/80 hover:bg-gray-700 text-gray-300 hover:text-white transition-colors flex items-center gap-1.5 border border-gray-700"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reset Chat</span>
            </button>
          )}
        </div>
      </div>

      {/* Error banner */}
      {errorBanner && (
        <div className="mx-6 mt-4 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-center gap-2.5 animate-fade-in">
          <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
          <span className="flex-1">{errorBanner}</span>
          <button
            onClick={() => setErrorBanner(null)}
            className="text-red-400 hover:text-red-200 text-xs font-semibold"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Message stream */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-lg mx-auto py-12 animate-fade-in">
            <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center mb-5 shadow-inner">
              <Bot className="w-8 h-8" />
            </div>
            <h2 className="text-xl font-bold text-white mb-2">
              Knowledge-Base AI Assistant
            </h2>
            <p className="text-sm text-gray-400 mb-8 leading-relaxed">
              Ask questions grounded strictly in the verified knowledge base. Every answer cites exact source documents and pages.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full">
              {[
                'What is collision resistance in a cryptographic hash function?',
                'What is a Merkle tree and how does it verify transactions?',
                'What is puzzle friendliness in blockchain systems?',
                'Hi! What topics can you answer questions about?',
              ].map((suggestion, i) => (
                <button
                  key={i}
                  onClick={() => handleSendMessage(suggestion)}
                  className="p-3.5 rounded-xl text-left text-xs text-gray-300 bg-gray-900/60 hover:bg-gray-800/80 border border-gray-800 hover:border-emerald-500/40 transition-all duration-200 group flex items-start gap-2.5"
                >
                  <Sparkles className="w-3.5 h-3.5 text-emerald-400 mt-0.5 flex-shrink-0 group-hover:scale-110 transition-transform" />
                  <span className="line-clamp-2">{suggestion}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg) => {
            const isUser = msg.role === 'user';
            return (
              <div
                key={msg.id}
                className={`flex gap-3.5 max-w-3xl ${
                  isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'
                } animate-fade-in`}
              >
                {/* Avatar */}
                <div
                  className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 border ${
                    isUser
                      ? 'bg-indigo-600/20 text-indigo-300 border-indigo-500/30'
                      : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  }`}
                >
                  {isUser ? <UserIcon className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                </div>

                {/* Message bubble */}
                <div className="flex flex-col gap-1.5 max-w-[85%]">
                  <div
                    className={`p-4 rounded-2xl text-sm leading-relaxed shadow-sm ${
                      isUser
                        ? 'bg-indigo-600/20 border border-indigo-500/30 text-white rounded-tr-none'
                        : msg.isRetracted
                        ? 'bg-amber-500/10 border border-amber-500/20 text-amber-200 rounded-tl-none'
                        : 'bg-gray-900/80 border border-gray-800/90 text-gray-100 rounded-tl-none'
                    }`}
                  >
                    {renderMessageContent(msg.content, msg.citations)}

                    {msg.isStreaming && (
                      <span className="typing-cursor" aria-hidden="true" />
                    )}
                  </div>

                  {/* Citations bar underneath assistant message */}
                  {!isUser && msg.citations && msg.citations.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5 pt-1 pl-1">
                      <span className="text-[11px] text-gray-500 font-medium flex items-center gap-1 mr-1">
                        <BookOpen className="w-3 h-3 text-emerald-400" />
                        Sources:
                      </span>
                      {msg.citations.map((cite, i) => (
                        <button
                          key={`${cite.chunk_id}-${i}`}
                          type="button"
                          onClick={() => handleOpenDrawer(msg.citations!, cite.tag)}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/20 hover:border-emerald-500/40 transition-all duration-150"
                        >
                          <FileText className="w-3 h-3 text-emerald-400" />
                          <span className="truncate max-w-[150px]">{cite.document}</span>
                          {cite.page !== null && cite.page !== undefined && (
                            <span className="text-[10px] text-emerald-400/80">p.{cite.page}</span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input container */}
      <div className="p-4 border-t border-gray-800 glass-panel">
        <div className="max-w-3xl mx-auto">
          <div className="relative glass-panel-elevated rounded-2xl border border-gray-700/80 focus-within:border-emerald-500/50 shadow-lg overflow-hidden transition-all duration-200">
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              disabled={isStreaming}
              rows={1}
              placeholder={
                isStreaming
                  ? 'Generating grounded answer...'
                  : 'Ask a question from the knowledge base (Enter to send, Shift+Enter for newline)...'
              }
              className="w-full pl-4 pr-14 py-3.5 bg-transparent text-sm text-white placeholder-gray-500 focus:outline-none resize-none max-h-36 disabled:opacity-50 disabled:cursor-not-allowed"
            />

            <button
              id="send-message-btn"
              type="button"
              onClick={() => handleSendMessage()}
              disabled={isStreaming || !inputValue.trim()}
              className="absolute right-2.5 bottom-2.5 w-9 h-9 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white flex items-center justify-center transition-all duration-150 shadow-md shadow-emerald-500/20 disabled:opacity-30 disabled:cursor-not-allowed disabled:bg-gray-800"
              title="Send Message"
            >
              {isStreaming ? (
                <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </button>
          </div>
          <div className="flex items-center justify-between text-[11px] text-gray-500 mt-2 px-1">
            <span>Only answers grounded in indexed documents with strict citations.</span>
            <span>Shift+Enter for new line</span>
          </div>
        </div>
      </div>

      {/* Citations slide-over drawer */}
      <CitationsDrawer
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        citations={activeCitations}
        activeTag={activeCitationTag}
      />
    </div>
  );
}
