'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import AdminDocManager from '@/components/AdminDocManager';
import {
  Shield,
  ShieldAlert,
  ArrowLeft,
  LogOut,
  Sparkles,
  Loader2,
} from 'lucide-react';

export default function AdminPage() {
  const router = useRouter();
  const { user, isLoading, logout } = useAuth();

  useEffect(() => {
    if (!isLoading && !user) {
      router.push('/login');
    }
  }, [user, isLoading, router]);

  if (isLoading || (!user && typeof window !== 'undefined')) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-background text-emerald-400 gap-3">
        <Loader2 className="w-8 h-8 animate-spin" />
        <p className="text-xs text-gray-400">Verifying administrator privileges...</p>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  // Non-admin Access Denied View
  if (user.role !== 'admin') {
    return (
      <main className="min-h-screen flex items-center justify-center p-4 bg-background">
        <div className="w-full max-w-md glass-panel p-8 rounded-2xl shadow-2xl text-center border border-red-500/20 animate-fade-in">
          <div className="w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-center justify-center mx-auto mb-4">
            <ShieldAlert className="w-8 h-8" />
          </div>
          <h1 className="text-xl font-bold text-white mb-2">403 - Access Denied</h1>
          <p className="text-sm text-gray-300 leading-relaxed mb-2">
            Administrator privileges required.
          </p>
          <p className="text-xs text-gray-500 leading-relaxed mb-6">
            Your current account (<span className="text-gray-300">{user.email}</span>) does not have permission to manage knowledge base documents.
          </p>
          <button
            onClick={() => router.push('/')}
            className="w-full py-3 px-4 rounded-xl bg-gray-800 hover:bg-gray-700 text-white text-xs font-semibold flex items-center justify-center gap-2 transition-colors border border-gray-700"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Return to Chat Interface</span>
          </button>
        </div>
      </main>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-background">
      {/* Admin Navbar */}
      <header className="h-16 px-6 border-b border-gray-800 glass-panel sticky top-0 z-30 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center">
            <Shield className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
              <span>Admin Document Portal</span>
              <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 uppercase">
                Admin
              </span>
            </h1>
            <p className="text-[11px] text-gray-400">Knowledge Base Ingestion & Lifecycle</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push('/')}
            className="px-3.5 py-2 rounded-xl bg-gray-900/80 hover:bg-gray-800 text-gray-300 hover:text-white border border-gray-800 text-xs font-semibold flex items-center gap-2 transition-all shadow-sm"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Back to Chat</span>
          </button>

          <div className="h-5 w-px bg-gray-800" />

          <div className="text-right hidden sm:block">
            <span className="text-xs text-white font-medium block truncate max-w-[180px]">
              {user.email}
            </span>
            <span className="text-[10px] text-emerald-400 font-semibold uppercase">Administrator</span>
          </div>

          <button
            onClick={logout}
            className="p-2 rounded-xl text-gray-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
            title="Sign Out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 p-6 md:p-8">
        <AdminDocManager />
      </main>
    </div>
  );
}
