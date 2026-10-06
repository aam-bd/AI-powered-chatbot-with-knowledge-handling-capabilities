'use client';

import React from 'react';
import { CitationItem } from '@/types/chat';
import { X, FileText, CheckCircle2, Bookmark, Layers, Hash } from 'lucide-react';

interface CitationsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  citations: CitationItem[];
  activeTag?: string | null;
}

export default function CitationsDrawer({
  isOpen,
  onClose,
  citations,
  activeTag,
}: CitationsDrawerProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden animate-fade-in">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-md glass-panel-elevated shadow-2xl border-l border-gray-800 flex flex-col animate-slide-in-right">
          {/* Header */}
          <div className="p-6 border-b border-gray-800 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center">
                <Bookmark className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-white">Verified Citations</h2>
                <p className="text-xs text-gray-400">
                  {citations.length} verified source excerpt{citations.length === 1 ? '' : 's'}
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800/80 transition-colors"
              aria-label="Close drawer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Citation items */}
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {citations.length === 0 ? (
              <div className="text-center py-12 text-gray-400 text-sm">
                No citations available for this message.
              </div>
            ) : (
              citations.map((cite, idx) => {
                const isSelected = activeTag === cite.tag;
                return (
                  <div
                    key={`${cite.chunk_id}-${idx}`}
                    className={`p-4 rounded-xl border transition-all duration-200 ${
                      isSelected
                        ? 'bg-emerald-500/10 border-emerald-500/40 shadow-lg shadow-emerald-500/10'
                        : 'bg-gray-900/60 border-gray-800 hover:border-gray-700'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                        <Hash className="w-3 h-3" />
                        {cite.tag}
                      </span>
                      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-400">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Grounded
                      </span>
                    </div>

                    <div className="space-y-2.5 text-xs text-gray-300">
                      <div className="flex items-start gap-2">
                        <FileText className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" />
                        <div>
                          <div className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold">
                            Document
                          </div>
                          <div className="font-medium text-white break-all">
                            {cite.document || 'Unknown Document'}
                          </div>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-3 pt-1">
                        <div>
                          <div className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold">
                            Page
                          </div>
                          <div className="font-medium text-white">
                            {cite.page !== null && cite.page !== undefined ? cite.page : 'N/A'}
                          </div>
                        </div>

                        <div>
                          <div className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold">
                            Section
                          </div>
                          <div className="font-medium text-white truncate" title={cite.section || 'General'}>
                            {cite.section || 'General'}
                          </div>
                        </div>
                      </div>

                      <div className="pt-2 border-t border-gray-800/80">
                        <div className="flex items-center gap-1.5 text-[10px] text-gray-400 font-mono">
                          <Layers className="w-3 h-3 text-gray-500" />
                          <span className="truncate" title={cite.chunk_id}>
                            ID: {cite.chunk_id}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Footer note */}
          <div className="p-4 border-t border-gray-800/80 bg-gray-950/40 text-[11px] text-gray-400 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
            <span>Strict 3-layer grounding ensures answers stem exclusively from these citations.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
