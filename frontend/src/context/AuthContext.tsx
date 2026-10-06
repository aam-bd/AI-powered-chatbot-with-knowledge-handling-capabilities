'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { User } from '@/types/chat';
import {
  getAccessToken,
  loginUser,
  getCurrentUser,
  clearTokens,
  refreshAccessToken,
} from '@/services/api';

interface AuthContextType {
  user: User | null;
  accessToken: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const initAuth = async () => {
    try {
      const token = getAccessToken();
      if (!token) {
        setUser(null);
        setAccessToken(null);
        setIsLoading(false);
        return;
      }

      setAccessToken(token);
      try {
        const currentUser = await getCurrentUser();
        setUser(currentUser);
      } catch (err) {
        // Try refreshing if token expired
        const refreshed = await refreshAccessToken();
        if (refreshed) {
          setAccessToken(refreshed);
          const currentUser = await getCurrentUser();
          setUser(currentUser);
        } else {
          clearTokens();
          setUser(null);
          setAccessToken(null);
        }
      }
    } catch {
      clearTokens();
      setUser(null);
      setAccessToken(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    initAuth();
  }, []);

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const tokens = await loginUser(email, password);
      setAccessToken(tokens.access_token);
      const currentUser = await getCurrentUser();
      setUser(currentUser);
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    clearTokens();
    setUser(null);
    setAccessToken(null);
  };

  const refreshAuth = async () => {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      setAccessToken(refreshed);
      const currentUser = await getCurrentUser();
      setUser(currentUser);
    } else {
      logout();
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        accessToken,
        isLoading,
        login,
        logout,
        refreshAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
