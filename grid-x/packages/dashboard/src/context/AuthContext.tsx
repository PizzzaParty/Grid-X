'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { API_HEADERS } from '@/lib/api';

interface User {
  id: number;
  email: string;
  role: 'buyer' | 'seller';
  credits: number;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  mounted: boolean;
  setUser: (user: User | null) => void;
  login: (user: User, token: string) => void;
  logout: () => void;
  /** Authenticated fetch — automatically attaches the JWT Authorization header. */
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  // mounted prevents the server-rendered HTML from differing from the first
  // client render. localStorage is only available in the browser, so we wait
  // until after hydration before reading it.
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const storedUser = localStorage.getItem('user');
    const storedToken = localStorage.getItem('token');
    if (storedUser && storedToken) {
      setUserState(JSON.parse(storedUser));
      setToken(storedToken);
    }
    setMounted(true);
  }, []);

  const login = (user: User, token: string) => {
    setUserState(user);
    setToken(token);
    localStorage.setItem('user', JSON.stringify(user));
    localStorage.setItem('token', token);
  };

  const logout = () => {
    setUserState(null);
    setToken(null);
    localStorage.removeItem('user');
    localStorage.removeItem('token');
  };

  const setUser = (user: User | null) => {
    setUserState(user);
    if (user) {
      localStorage.setItem('user', JSON.stringify(user));
    } else {
      logout();
    }
  };

  /**
   * Wrapper around fetch that injects the JWT Authorization header and
   * the shared API headers (e.g. ngrok bypass). Use this for all
   * authenticated API calls instead of raw fetch().
   */
  const authFetch = (url: string, options: RequestInit = {}): Promise<Response> => {
    const headers = {
      ...API_HEADERS,
      ...(options.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
    return fetch(url, { ...options, headers });
  };

  return (
    <AuthContext.Provider value={{ user, token, mounted, setUser, login, logout, authFetch }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
