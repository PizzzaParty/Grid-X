'use client';

import { useAuth } from '@/context/AuthContext';
import Sidebar from '@/components/Sidebar';
import styles from './dashboardLayout.module.css';

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { mounted } = useAuth();

  // Don't render anything until localStorage has been read on the client.
  // This prevents a React hydration mismatch between the server-rendered HTML
  // (where user is always null) and the first client render (where user may
  // already be set from localStorage).
  if (!mounted) return null;

  return (
    <div className={styles.wrapper}>
      <Sidebar />
      <main className={styles.content}>
        {children}
      </main>
    </div>
  );
}
