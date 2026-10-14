'use client';

import React, { useEffect, useRef } from 'react';
import {
  useAccessibility,
  ThemeType,
  FontSizeType,
  FontFamilyType,
} from '@/context/AccessibilityContext';
import {
  X,
  Sun,
  Moon,
  Sparkles,
  Contrast,
  Sliders,
  Type,
  RotateCcw,
  Check,
  Eye,
  ZapOff,
} from 'lucide-react';

export default function AccessibilityModal() {
  const {
    theme,
    setTheme,
    fontSize,
    setFontSize,
    fontFamily,
    setFontFamily,
    reducedMotion,
    setReducedMotion,
    highContrastFocus,
    setHighContrastFocus,
    isModalOpen,
    setIsModalOpen,
    resetToDefaults,
  } = useAccessibility();

  const modalRef = useRef<HTMLDivElement>(null);

  // Close on Escape key
  useEffect(() => {
    if (!isModalOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsModalOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isModalOpen, setIsModalOpen]);

  if (!isModalOpen) return null;

  const themes: {
    id: ThemeType;
    label: string;
    desc: string;
    icon: React.ReactNode;
    bgClass: string;
    borderClass: string;
    textClass: string;
  }[] = [
    {
      id: 'dark',
      label: 'Modern Dark',
      desc: 'Balanced slate palette with high-contrast text',
      icon: <Moon className="w-4 h-4 text-emerald-400" />,
      bgClass: 'bg-[#111827]',
      borderClass: 'border-slate-700',
      textClass: 'text-slate-100',
    },
    {
      id: 'light',
      label: 'Clean Light',
      desc: 'Paper-white background with deep charcoal text',
      icon: <Sun className="w-4 h-4 text-amber-500" />,
      bgClass: 'bg-white',
      borderClass: 'border-slate-300',
      textClass: 'text-slate-900',
    },
    {
      id: 'high-contrast',
      label: 'High Contrast',
      desc: 'WCAG AAA black & white with safety amber accents',
      icon: <Contrast className="w-4 h-4 text-yellow-400" />,
      bgClass: 'bg-black',
      borderClass: 'border-white',
      textClass: 'text-white',
    },
    {
      id: 'midnight',
      label: 'Midnight OLED',
      desc: 'Pitch black background optimized for OLED displays',
      icon: <Sparkles className="w-4 h-4 text-sky-400" />,
      bgClass: 'bg-black',
      borderClass: 'border-slate-800',
      textClass: 'text-sky-100',
    },
  ];

  const fontSizes: { id: FontSizeType; label: string; scale: string; px: string }[] = [
    { id: 'normal', label: 'Default', scale: '100%', px: '16px base' },
    { id: 'medium', label: 'Medium', scale: '112%', px: '18px base' },
    { id: 'large', label: 'Large', scale: '125%', px: '20px base' },
    { id: 'xl', label: 'Extra Large', scale: '140%', px: '22px base' },
  ];

  const fontFamilies: {
    id: FontFamilyType;
    label: string;
    family: string;
    sample: string;
  }[] = [
    {
      id: 'sans',
      label: 'Modern Clean Sans',
      family: 'Inter / System Sans',
      sample: 'Clear, modern, and highly legible for screen reading.',
    },
    {
      id: 'serif',
      label: 'Readable Editorial Serif',
      family: 'Merriweather / Georgia',
      sample: 'Distinct character shapes designed for extended reading.',
    },
    {
      id: 'dyslexic',
      label: 'Dyslexic-Friendly',
      family: 'Atkinson / OpenDyslexic style',
      sample: 'High-aperture forms with wide character differentiation.',
    },
    {
      id: 'mono',
      label: 'Technical Monospace',
      family: 'JetBrains / Cascadia Code',
      sample: 'Even character widths for technical and structured inspection.',
    },
  ];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="a11y-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget) setIsModalOpen(false);
      }}
    >
      <div
        ref={modalRef}
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto glass-panel-elevated rounded-2xl border border-slate-700/80 p-6 md:p-8 shadow-2xl space-y-6 text-slate-100"
      >
        {/* Header */}
        <div className="flex items-start justify-between pb-4 border-b border-slate-700/70">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center justify-center">
              <Eye className="w-5 h-5" />
            </div>
            <div>
              <h2 id="a11y-modal-title" className="text-lg font-bold text-white tracking-tight">
                Display & Accessibility Options
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Customize appearance, font size scaling, and typography for your comfort.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setIsModalOpen(false)}
            className="touch-target p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            title="Close Settings (Escape)"
            aria-label="Close accessibility options"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Section 1: Themes */}
        <section className="space-y-3">
          <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block">
            Color Scheme & Theme
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {themes.map((t) => {
              const isSelected = theme === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTheme(t.id)}
                  className={`p-3.5 rounded-xl border text-left transition-all relative flex flex-col justify-between ${
                    isSelected
                      ? 'border-emerald-400 ring-2 ring-emerald-400/30 bg-slate-800/90'
                      : 'border-slate-700/80 hover:border-slate-500 bg-slate-900/60'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2 font-semibold text-sm text-white">
                      {t.icon}
                      <span>{t.label}</span>
                    </div>
                    {isSelected && (
                      <span className="w-5 h-5 rounded-full bg-emerald-500 text-slate-950 flex items-center justify-center">
                        <Check className="w-3.5 h-3.5 stroke-[3]" />
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 leading-normal">{t.desc}</p>
                </button>
              );
            })}
          </div>
        </section>

        {/* Section 2: Font Size Scaling */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Text Size Scaling
            </label>
            <span className="text-xs text-emerald-400 font-mono font-semibold">
              {fontSizes.find((f) => f.id === fontSize)?.scale} ({fontSizes.find((f) => f.id === fontSize)?.px})
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {fontSizes.map((f) => {
              const isSelected = fontSize === f.id;
              return (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setFontSize(f.id)}
                  className={`py-3 px-2 rounded-xl border text-center transition-all ${
                    isSelected
                      ? 'border-emerald-400 bg-emerald-500/20 text-emerald-300 font-bold'
                      : 'border-slate-700/80 bg-slate-900/60 hover:bg-slate-800 text-slate-300'
                  }`}
                >
                  <div className="text-base font-semibold">{f.scale}</div>
                  <div className="text-xs text-slate-400 mt-0.5">{f.label}</div>
                </button>
              );
            })}
          </div>
        </section>

        {/* Section 3: Font Family */}
        <section className="space-y-3">
          <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block">
            Typography Style
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {fontFamilies.map((ff) => {
              const isSelected = fontFamily === ff.id;
              return (
                <button
                  key={ff.id}
                  type="button"
                  onClick={() => setFontFamily(ff.id)}
                  className={`p-3.5 rounded-xl border text-left transition-all ${
                    isSelected
                      ? 'border-emerald-400 ring-2 ring-emerald-400/30 bg-slate-800/90'
                      : 'border-slate-700/80 hover:border-slate-500 bg-slate-900/60'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-semibold text-sm text-white">{ff.label}</span>
                    {isSelected && (
                      <span className="w-5 h-5 rounded-full bg-emerald-500 text-slate-950 flex items-center justify-center">
                        <Check className="w-3.5 h-3.5 stroke-[3]" />
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 line-clamp-1 italic">{ff.family}</p>
                </button>
              );
            })}
          </div>
        </section>

        {/* Section 4: Motion & High Contrast Focus */}
        <section className="space-y-3 pt-1 border-t border-slate-700/60">
          <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block">
            Motion & Focus Indicators
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {/* Reduced motion */}
            <label className="p-3.5 rounded-xl border border-slate-700/80 bg-slate-900/60 hover:bg-slate-800/80 transition-all flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={reducedMotion}
                onChange={(e) => setReducedMotion(e.target.checked)}
                className="mt-1 w-4 h-4 rounded text-emerald-500 border-slate-700 focus:ring-emerald-400"
              />
              <div className="text-xs">
                <span className="font-semibold text-white block">Reduce Motion</span>
                <span className="text-slate-400 leading-normal block mt-0.5">
                  Minimizes transitions, sliding movements, and cursor pulsing.
                </span>
              </div>
            </label>

            {/* High-contrast focus */}
            <label className="p-3.5 rounded-xl border border-slate-700/80 bg-slate-900/60 hover:bg-slate-800/80 transition-all flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={highContrastFocus}
                onChange={(e) => setHighContrastFocus(e.target.checked)}
                className="mt-1 w-4 h-4 rounded text-emerald-500 border-slate-700 focus:ring-emerald-400"
              />
              <div className="text-xs">
                <span className="font-semibold text-white block">Prominent Focus Outlines</span>
                <span className="text-slate-400 leading-normal block mt-0.5">
                  Enforces distinct 3px colored rings on all keyboard-focused elements.
                </span>
              </div>
            </label>
          </div>
        </section>

        {/* Section 5: Live Reading Preview */}
        <section className="p-4 rounded-xl border border-slate-700/80 bg-slate-900/80 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400 font-semibold uppercase tracking-wider">
            <span>Live Reading Sample</span>
            <span className="text-emerald-400 font-mono text-[11px]">Real-Time Rendering</span>
          </div>
          <div className="p-3.5 rounded-xl border border-slate-700 bg-slate-950/60 text-slate-100 space-y-1.5">
            <p className="text-sm font-semibold text-white">
              Grounded AI Response:
            </p>
            <p className="text-sm leading-relaxed text-slate-200">
              A cryptographic hash function provides pre-image resistance and collision resistance. Every transaction in a block is organized in a Merkle tree{' '}
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                [C1]
              </span>.
            </p>
          </div>
        </section>

        {/* Footer Actions */}
        <div className="flex items-center justify-between pt-4 border-t border-slate-700/70">
          <button
            type="button"
            onClick={resetToDefaults}
            className="text-xs font-medium text-slate-400 hover:text-white flex items-center gap-1.5 transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Reset to Defaults</span>
          </button>

          <button
            type="button"
            onClick={() => setIsModalOpen(false)}
            className="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition-colors shadow-md shadow-emerald-500/20"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
