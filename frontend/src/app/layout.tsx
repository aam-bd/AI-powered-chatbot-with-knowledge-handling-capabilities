import type { Metadata } from 'next';
import './globals.css';
import { AuthProvider } from '@/context/AuthContext';

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
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background text-gray-100 antialiased selection:bg-emerald-500/30 selection:text-emerald-200">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
