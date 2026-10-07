'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import AccountView from '@/components/AccountView';
import { Loader2 } from 'lucide-react';

export default function AccountPage() {
  const router = useRouter();
  const { user, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading && !user) {
      router.push('/login');
    }
  }, [user, isLoading, router]);

  if (isLoading || !user) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-background text-emerald-400 gap-3">
        <Loader2 className="w-8 h-8 animate-spin" />
        <p className="text-xs text-gray-400">Loading account...</p>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-background p-6 md:p-12 flex flex-col items-center justify-center relative">
      <AccountView />
    </main>
  );
}
