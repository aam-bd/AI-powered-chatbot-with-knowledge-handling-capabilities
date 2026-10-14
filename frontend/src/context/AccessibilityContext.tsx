'use client';

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

export type ThemeType = 'dark' | 'light' | 'high-contrast' | 'midnight';
export type FontSizeType = 'normal' | 'medium' | 'large' | 'xl';
export type FontFamilyType = 'sans' | 'serif' | 'dyslexic' | 'mono';

export interface AccessibilityPreferences {
  theme: ThemeType;
  fontSize: FontSizeType;
  fontFamily: FontFamilyType;
  reducedMotion: boolean;
  highContrastFocus: boolean;
}

export const DEFAULT_PREFERENCES: AccessibilityPreferences = {
  theme: 'dark',
  fontSize: 'normal',
  fontFamily: 'sans',
  reducedMotion: false,
  highContrastFocus: false,
};

interface AccessibilityContextType extends AccessibilityPreferences {
  setTheme: (theme: ThemeType) => void;
  setFontSize: (size: FontSizeType) => void;
  setFontFamily: (font: FontFamilyType) => void;
  setReducedMotion: (reduced: boolean) => void;
  setHighContrastFocus: (enabled: boolean) => void;
  isModalOpen: boolean;
  setIsModalOpen: (open: boolean) => void;
  resetToDefaults: () => void;
}

const STORAGE_KEY = 'kb_accessibility_preferences';

const AccessibilityContext = createContext<AccessibilityContextType | undefined>(undefined);

export function AccessibilityProvider({ children }: { children: React.ReactNode }) {
  const [preferences, setPreferences] = useState<AccessibilityPreferences>(DEFAULT_PREFERENCES);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isMounted, setIsMounted] = useState(false);

  // Apply attributes to <html> root
  const applyPreferencesToDOM = useCallback((prefs: AccessibilityPreferences) => {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;

    // Theme: dark class for Tailwind darkMode: 'class', plus data-theme
    if (prefs.theme === 'light') {
      root.classList.remove('dark');
    } else {
      root.classList.add('dark');
    }
    root.setAttribute('data-theme', prefs.theme);
    root.setAttribute('data-font-size', prefs.fontSize);
    root.setAttribute('data-font-family', prefs.fontFamily);
    root.setAttribute('data-reduced-motion', prefs.reducedMotion ? 'true' : 'false');
    root.setAttribute('data-high-contrast-focus', prefs.highContrastFocus ? 'true' : 'false');
  }, []);

  // Initialize preferences on mount
  useEffect(() => {
    setIsMounted(true);
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        const merged: AccessibilityPreferences = {
          theme: ['dark', 'light', 'high-contrast', 'midnight'].includes(parsed.theme)
            ? parsed.theme
            : DEFAULT_PREFERENCES.theme,
          fontSize: ['normal', 'medium', 'large', 'xl'].includes(parsed.fontSize)
            ? parsed.fontSize
            : DEFAULT_PREFERENCES.fontSize,
          fontFamily: ['sans', 'serif', 'dyslexic', 'mono'].includes(parsed.fontFamily)
            ? parsed.fontFamily
            : DEFAULT_PREFERENCES.fontFamily,
          reducedMotion: typeof parsed.reducedMotion === 'boolean'
            ? parsed.reducedMotion
            : DEFAULT_PREFERENCES.reducedMotion,
          highContrastFocus: typeof parsed.highContrastFocus === 'boolean'
            ? parsed.highContrastFocus
            : DEFAULT_PREFERENCES.highContrastFocus,
        };
        setPreferences(merged);
        applyPreferencesToDOM(merged);
        return;
      }
    } catch {
      // ignore JSON or storage errors
    }

    // Default: detect system preferences if no stored configuration
    if (typeof window !== 'undefined') {
      const prefersDark =
        typeof window.matchMedia === 'function'
          ? window.matchMedia('(prefers-color-scheme: dark)').matches
          : true;
      const prefersReducedMotion =
        typeof window.matchMedia === 'function'
          ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
          : false;
      const initial: AccessibilityPreferences = {
        ...DEFAULT_PREFERENCES,
        theme: prefersDark ? 'dark' : 'light',
        reducedMotion: prefersReducedMotion,
      };
      setPreferences(initial);
      applyPreferencesToDOM(initial);
    }
  }, [applyPreferencesToDOM]);

  // Persist and apply changes
  const updatePreference = <K extends keyof AccessibilityPreferences>(
    key: K,
    value: AccessibilityPreferences[K]
  ) => {
    setPreferences((prev) => {
      const updated = { ...prev, [key]: value };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      } catch {
        // ignore storage errors
      }
      applyPreferencesToDOM(updated);
      return updated;
    });
  };

  const setTheme = (theme: ThemeType) => updatePreference('theme', theme);
  const setFontSize = (fontSize: FontSizeType) => updatePreference('fontSize', fontSize);
  const setFontFamily = (fontFamily: FontFamilyType) => updatePreference('fontFamily', fontFamily);
  const setReducedMotion = (reducedMotion: boolean) => updatePreference('reducedMotion', reducedMotion);
  const setHighContrastFocus = (highContrastFocus: boolean) =>
    updatePreference('highContrastFocus', highContrastFocus);

  const resetToDefaults = () => {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    setPreferences(DEFAULT_PREFERENCES);
    applyPreferencesToDOM(DEFAULT_PREFERENCES);
  };

  // Keyboard shortcut: Alt + A or Option + A toggles the Accessibility Modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.altKey && (e.key === 'a' || e.key === 'A')) {
        e.preventDefault();
        setIsModalOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <AccessibilityContext.Provider
      value={{
        ...preferences,
        setTheme,
        setFontSize,
        setFontFamily,
        setReducedMotion,
        setHighContrastFocus,
        isModalOpen,
        setIsModalOpen,
        resetToDefaults,
      }}
    >
      {children}
    </AccessibilityContext.Provider>
  );
}

export function useAccessibility() {
  const context = useContext(AccessibilityContext);
  if (!context) {
    throw new Error('useAccessibility must be used within an AccessibilityProvider');
  }
  return context;
}
