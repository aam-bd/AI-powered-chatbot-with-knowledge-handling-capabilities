import type { Metadata } from 'next';
import './globals.css';
import { AuthProvider } from '@/context/AuthContext';
import { AccessibilityProvider } from '@/context/AccessibilityContext';

import AccessibilityModal from '@/components/AccessibilityModal';

export const metadata: Metadata = {
  title: 'Knowledge-Base AI Chatbot',
  description: 'Grounded enterprise RAG chatbot with strict document citations and 3-layer hallucination guards.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var stored = localStorage.getItem('kb_accessibility_preferences');
                  if (stored) {
                    var prefs = JSON.parse(stored);
                    var root = document.documentElement;
                    if (prefs.theme === 'light') {
                      root.classList.remove('dark');
                    } else {
                      root.classList.add('dark');
                    }
                    if (prefs.theme) root.setAttribute('data-theme', prefs.theme);
                    if (prefs.fontSize) root.setAttribute('data-font-size', prefs.fontSize);
                    if (prefs.fontFamily) root.setAttribute('data-font-family', prefs.fontFamily);
                    if (prefs.reducedMotion) root.setAttribute('data-reduced-motion', 'true');
                    if (prefs.highContrastFocus) root.setAttribute('data-high-contrast-focus', 'true');
                  }
                } catch (e) {}
              })();
            `,
          }}
        />
      </head>
      <body className="min-h-screen bg-background text-gray-100 antialiased selection:bg-emerald-500/30 selection:text-emerald-200">
        <AccessibilityProvider>
          <AuthProvider>
            {children}
            <AccessibilityModal />
          </AuthProvider>
        </AccessibilityProvider>
      </body>
    </html>
  );
}
