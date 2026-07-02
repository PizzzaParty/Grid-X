'use client';

import { useEffect, useState } from 'react';
import styles from './seller.module.css';
import { API_BASE } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

interface Agent {
  id: string;
  status: 'IDLE' | 'BUSY' | 'OFFLINE';
  gpu_model: string;
  ram_total: string;
  last_heartbeat: string;
}

interface SellerTask {
  id: number;
  job_id: number;
  assigned_to: string;
  status: 'COMPLETED';
  completed_at: string;
}

export default function SellerDashboard() {
  const { user, authFetch } = useAuth();

  const [agents, setAgents] = useState<Agent[]>([]);
  const [tasks, setTasks] = useState<SellerTask[]>([]);
  const [jobsCompleted, setJobsCompleted] = useState(0);
  const [credits, setCredits] = useState<number | null>(null);

  const fetchWallet = async () => {
    if (!user) return;
    const res = await authFetch(`${API_BASE}/auth/wallet/${user.id}`);
    if (!res.ok) { console.error(await res.text()); return; }
    const data = await res.json();
    setCredits(data.credits);
  };

  /* ================= My Agents ================= */
  const fetchMyAgents = async () => {
    if (!user) return;
    const res = await authFetch(`${API_BASE}/stats/my-agents/${user.id}`);
    if (!res.ok) return;
    const data = await res.json();
    setAgents(data.agents || []);
  };

  /* ================= Seller Tasks ================= */
  const fetchSellerTasks = async () => {
    if (!user) return;
    const res = await authFetch(`${API_BASE}/stats/seller-tasks/${user.id}`);
    if (!res.ok) return;
    const data = await res.json();
    setTasks(data.tasks || []);
    setJobsCompleted(data.total_completed || 0);
  };

  /* ================= Polling ================= */
  useEffect(() => {
    if (!user) return;

    fetchWallet();
    fetchMyAgents();
    fetchSellerTasks();

    const interval = setInterval(() => {
      fetchWallet();
      fetchMyAgents();
      fetchSellerTasks();
    }, 5000);

    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  /* ================= Status Mapping ================= */
  const getStatusLabel = (status: Agent['status']) => {
    if (status === 'BUSY') return 'Running';
    if (status === 'IDLE') return 'Inactive';
    return 'Offline';
  };

  /* ================= UI ================= */
  return (
    <div className={styles.dashboard}>
      {/* Header Section */}
      <div className={styles.header}>
        <div className={styles.titleWrapper}>
          <h1 className={styles.providerText}>Provider</h1>
          <h1 className={styles.dashboardText}>Dashboard</h1>
        </div>

        <div className={styles.statsRow}>
          <div className={styles.statCard}>
            <span>Wallet Balance</span>
            <strong>
              {credits !== null ? `${credits} credits` : '0'}
            </strong>
          </div>

          <div className={styles.statCard}>
            <span>Jobs Completed</span>
            <strong>{jobsCompleted}</strong>
          </div>
        </div>
      </div>

      {/* Cards Grid */}
      <div className={styles.cardsGrid}>
        {/* ─── My Agents ─── */}
        <section className={styles.card}>
          <h2>My Agents</h2>
          <p className={styles.muted}>Devices registered to your account</p>

          {agents.length === 0 && (
            <p className={styles.muted}>[No agents registered]</p>
          )}

          <ul className={styles.list}>
            {agents.map(agent => (
              <li key={agent.id} className={styles.agentRow}>
                <div>
                  <strong className={styles.flowText}>{agent.gpu_model}</strong>
                  <span className={`${styles.sub} ${styles.flowText}`}>{agent.ram_total}</span>
                </div>
                <span className={`${styles.status} ${styles.flowText}`}>
                  {getStatusLabel(agent.status)}
                </span>
              </li>
            ))}
          </ul>
        </section>

        {/* ─── Task History ─── */}
        <section className={styles.card}>
          <h2>Task History</h2>
          <p className={styles.muted}>Completed tasks executed by your agents</p>

          {tasks.length === 0 && (
            <p className={styles.muted}>[No completed tasks yet]</p>
          )}

          <ul className={styles.list}>
            {tasks.map(task => (
              <li key={task.id} className={styles.taskRow}>
                <span className={styles.flowText}>Job #{task.job_id}</span>
                <span className={`${styles.done} ${styles.flowText}`}>COMPLETED</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
