'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import styles from '../login/login.module.css'; // reuse login styles
import { API_BASE, API_HEADERS } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

export default function RegistrationPage() {
  const router = useRouter();
  const { login } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'buyer' | 'seller'>('buyer');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      // Step 1: Register the account
      const registerRes = await fetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...API_HEADERS },
        body: JSON.stringify({ email, password, role }),
      });

      if (!registerRes.ok) {
        const data = await registerRes.json().catch(() => ({}));
        setError(data.detail || 'Registration failed');
        return;
      }

      // Step 2: Auto-login so the user gets a JWT immediately
      const loginRes = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...API_HEADERS },
        body: JSON.stringify({ email, password }),
      });

      if (!loginRes.ok) {
        // Registration succeeded but login failed — send to login page
        router.push('/login');
        return;
      }

      const data = await loginRes.json();
      login(data.user, data.access_token);

      if (data.user.role === 'buyer') {
        router.push('/dashboard/buyer');
      } else {
        router.push('/dashboard/seller');
      }
    } catch (err) {
      console.error(err);
      setError('Cannot reach backend');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Create your Grid-X Account</h1>
      <p className={styles.subtitle}>Join the decentralized compute mesh</p>

      <form className={styles.card} onSubmit={handleSubmit}>
        <div className={styles.fields}>
          <div className={styles.field}>
            <label>Email</label>
            <input
              type="email"
              placeholder="user@domain.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className={styles.field}>
            <label>Password</label>
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <div className={styles.field}>
            <label>Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as 'buyer' | 'seller')}
            >
              <option value="buyer">Scientist (Buyer)</option>
              <option value="seller">Provider (Seller)</option>
            </select>
          </div>
        </div>

        {error && <p className={styles.error}>{error}</p>}

        <button type="submit" className={styles.primaryBtn} disabled={loading}>
          {loading ? 'Creating account…' : 'Register'}
        </button>
      </form>
    </div>
  );
}
