import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { AccessibilityProvider, useAccessibility } from '@/context/AccessibilityContext';
import AccessibilityModal from '../AccessibilityModal';
import AccessibilityTrigger from '../AccessibilityTrigger';

// Test consumer component to verify context methods
function TestConsumer() {
  const {
    theme,
    fontSize,
    fontFamily,
    reducedMotion,
    highContrastFocus,
    setTheme,
    setFontSize,
    setFontFamily,
    setReducedMotion,
    setHighContrastFocus,
    resetToDefaults,
    setIsModalOpen,
  } = useAccessibility();

  return (
    <div>
      <div data-testid="theme-val">{theme}</div>
      <div data-testid="fontsize-val">{fontSize}</div>
      <div data-testid="fontfamily-val">{fontFamily}</div>
      <div data-testid="reducedmotion-val">{reducedMotion ? 'true' : 'false'}</div>
      <div data-testid="focus-val">{highContrastFocus ? 'true' : 'false'}</div>

      <button onClick={() => setTheme('high-contrast')}>Set High Contrast</button>
      <button onClick={() => setTheme('light')}>Set Light</button>
      <button onClick={() => setTheme('midnight')}>Set Midnight</button>
      <button onClick={() => setFontSize('large')}>Set Large Font</button>
      <button onClick={() => setFontSize('xl')}>Set XL Font</button>
      <button onClick={() => setFontFamily('dyslexic')}>Set Dyslexic Font</button>
      <button onClick={() => setReducedMotion(true)}>Enable Reduced Motion</button>
      <button onClick={() => setHighContrastFocus(true)}>Enable Contrast Focus</button>
      <button onClick={resetToDefaults}>Reset Defaults</button>
      <button onClick={() => setIsModalOpen(true)}>Open Modal</button>
    </div>
  );
}

describe('Accessibility Options & UI/UX Suite', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.removeAttribute('data-font-size');
    document.documentElement.removeAttribute('data-font-family');
    document.documentElement.removeAttribute('data-reduced-motion');
    document.documentElement.removeAttribute('data-contrast-focus');
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('initializes with default accessibility preferences and sets document attributes', () => {
    render(
      <AccessibilityProvider>
        <TestConsumer />
      </AccessibilityProvider>
    );

    expect(screen.getByTestId('theme-val')).toHaveTextContent('dark');
    expect(screen.getByTestId('fontsize-val')).toHaveTextContent('normal');
    expect(screen.getByTestId('fontfamily-val')).toHaveTextContent('sans');
    expect(screen.getByTestId('reducedmotion-val')).toHaveTextContent('false');
    expect(screen.getByTestId('focus-val')).toHaveTextContent('false');

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(document.documentElement.getAttribute('data-font-size')).toBe('normal');
    expect(document.documentElement.getAttribute('data-font-family')).toBe('sans');
  });

  it('updates theme to high-contrast, light, and midnight, persisting to localStorage', () => {
    render(
      <AccessibilityProvider>
        <TestConsumer />
      </AccessibilityProvider>
    );

    // Switch to High Contrast
    fireEvent.click(screen.getByText('Set High Contrast'));
    expect(screen.getByTestId('theme-val')).toHaveTextContent('high-contrast');
    expect(document.documentElement.getAttribute('data-theme')).toBe('high-contrast');

    const stored = JSON.parse(localStorage.getItem('kb_accessibility_preferences') || '{}');
    expect(stored.theme).toBe('high-contrast');

    // Switch to Light
    fireEvent.click(screen.getByText('Set Light'));
    expect(screen.getByTestId('theme-val')).toHaveTextContent('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    // Switch to Midnight
    fireEvent.click(screen.getByText('Set Midnight'));
    expect(screen.getByTestId('theme-val')).toHaveTextContent('midnight');
    expect(document.documentElement.getAttribute('data-theme')).toBe('midnight');
  });

  it('updates font size to large and xl, adjusting root document attribute', () => {
    render(
      <AccessibilityProvider>
        <TestConsumer />
      </AccessibilityProvider>
    );

    fireEvent.click(screen.getByText('Set Large Font'));
    expect(screen.getByTestId('fontsize-val')).toHaveTextContent('large');
    expect(document.documentElement.getAttribute('data-font-size')).toBe('large');

    fireEvent.click(screen.getByText('Set XL Font'));
    expect(screen.getByTestId('fontsize-val')).toHaveTextContent('xl');
    expect(document.documentElement.getAttribute('data-font-size')).toBe('xl');

    const stored = JSON.parse(localStorage.getItem('kb_accessibility_preferences') || '{}');
    expect(stored.fontSize).toBe('xl');
  });

  it('updates font family to OpenDyslexic / dyslexic friendly', () => {
    render(
      <AccessibilityProvider>
        <TestConsumer />
      </AccessibilityProvider>
    );

    fireEvent.click(screen.getByText('Set Dyslexic Font'));
    expect(screen.getByTestId('fontfamily-val')).toHaveTextContent('dyslexic');
    expect(document.documentElement.getAttribute('data-font-family')).toBe('dyslexic');
  });

  it('toggles reduced motion and high-contrast focus indicators', () => {
    render(
      <AccessibilityProvider>
        <TestConsumer />
      </AccessibilityProvider>
    );

    fireEvent.click(screen.getByText('Enable Reduced Motion'));
    expect(screen.getByTestId('reducedmotion-val')).toHaveTextContent('true');
    expect(document.documentElement.getAttribute('data-reduced-motion')).toBe('true');

    fireEvent.click(screen.getByText('Enable Contrast Focus'));
    expect(screen.getByTestId('focus-val')).toHaveTextContent('true');
    expect(document.documentElement.getAttribute('data-high-contrast-focus')).toBe('true');
  });

  it('resets all preferences to default values', () => {
    render(
      <AccessibilityProvider>
        <TestConsumer />
      </AccessibilityProvider>
    );

    // Modify multiple settings
    fireEvent.click(screen.getByText('Set High Contrast'));
    fireEvent.click(screen.getByText('Set XL Font'));
    fireEvent.click(screen.getByText('Enable Reduced Motion'));

    expect(screen.getByTestId('theme-val')).toHaveTextContent('high-contrast');
    expect(screen.getByTestId('fontsize-val')).toHaveTextContent('xl');
    expect(screen.getByTestId('reducedmotion-val')).toHaveTextContent('true');

    // Click Reset
    fireEvent.click(screen.getByText('Reset Defaults'));

    expect(screen.getByTestId('theme-val')).toHaveTextContent('dark');
    expect(screen.getByTestId('fontsize-val')).toHaveTextContent('normal');
    expect(screen.getByTestId('fontfamily-val')).toHaveTextContent('sans');
    expect(screen.getByTestId('reducedmotion-val')).toHaveTextContent('false');
    expect(screen.getByTestId('focus-val')).toHaveTextContent('false');
  });

  it('renders AccessibilityModal and responds to theme selection and escape key', async () => {
    render(
      <AccessibilityProvider>
        <TestConsumer />
        <AccessibilityModal />
      </AccessibilityProvider>
    );

    // Modal is initially not open
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Open modal via button
    fireEvent.click(screen.getByText('Open Modal'));
    const modal = screen.getByRole('dialog');
    expect(modal).toBeInTheDocument();
    expect(within(modal).getByText('Display & Accessibility Options')).toBeInTheDocument();

    // Select theme in modal: High Contrast
    const highContrastBtn = within(modal).getByRole('button', { name: /^high contrast/i });
    fireEvent.click(highContrastBtn);
    expect(screen.getByTestId('theme-val')).toHaveTextContent('high-contrast');

    // Press Escape to close modal
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('renders AccessibilityTrigger button in navbar and opens modal on click', () => {
    render(
      <AccessibilityProvider>
        <AccessibilityTrigger variant="navbar" />
        <AccessibilityModal />
      </AccessibilityProvider>
    );

    const triggerBtn = screen.getByRole('button', { name: /open display and accessibility settings/i });
    expect(triggerBtn).toBeInTheDocument();

    fireEvent.click(triggerBtn);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});
