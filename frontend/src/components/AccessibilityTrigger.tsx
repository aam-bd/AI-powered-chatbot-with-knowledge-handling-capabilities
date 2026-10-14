'use client';

import React from 'react';
import { useAccessibility } from '@/context/AccessibilityContext';
import { Sliders, Eye, Type, Sparkles } from 'lucide-react';

interface AccessibilityTriggerProps {
  variant?: 'navbar' | 'sidebar' | 'icon-only';
  className?: string;
}

export default function AccessibilityTrigger({
  variant = 'navbar',
  className = '',
}: AccessibilityTriggerProps) {
  const { setIsModalOpen, theme } = useAccessibility();

  if (variant === 'icon-only') {
    return (
      <button
        type="button"
        onClick={() => setIsModalOpen(true)}
        className={`touch-target p-2 rounded-xl text-slate-300 hover:text-white hover:bg-slate-800/60 transition-colors border border-transparent hover:border-slate-700/60 ${className}`}
        title="Accessibility & Theme Settings (Alt+A)"
        aria-label="Accessibility and display settings"
      >
        <Eye className="w-4 h-4" />
      </button>
    );
  }

  if (variant === 'sidebar') {
    return (
      <button
        type="button"
        onClick={() => setIsModalOpen(true)}
        className={`w-full py-2 px-3 rounded-xl bg-slate-900/60 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-800 hover:border-emerald-500/40 text-xs font-medium flex items-center justify-between transition-all group ${className}`}
        title="Customize theme, font size, and contrast (Alt+A)"
        aria-label="Open accessibility options"
      >
        <div className="flex items-center gap-2">
          <Eye className="w-3.5 h-3.5 text-emerald-400 group-hover:scale-110 transition-transform" />
          <span>Accessibility</span>
        </div>
        <span className="text-[11px] font-mono text-slate-400 bg-slate-800/80 px-1.5 py-0.5 rounded border border-slate-700/60">
          Alt+A
        </span>
      </button>
    );
  }

  // Default navbar variant
  return (
    <button
      type="button"
      id="accessibility-options-btn"
      onClick={() => setIsModalOpen(true)}
      className={`px-3 py-1.5 rounded-xl bg-slate-900/70 hover:bg-slate-800 text-slate-200 hover:text-white border border-slate-800 hover:border-emerald-500/40 text-xs font-medium flex items-center gap-2 transition-all shadow-sm ${className}`}
      title="Display & Accessibility Options (Alt+A)"
      aria-label="Open display and accessibility settings"
    >
      <Eye className="w-3.5 h-3.5 text-emerald-400" />
      <span className="hidden sm:inline">Accessibility</span>
      <span className="hidden md:inline text-[11px] font-mono text-slate-400 bg-slate-800/90 px-1.5 py-0.2 rounded border border-slate-700">
        Alt+A
      </span>
    </button>
  );
}
