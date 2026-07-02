'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import styles from './login.module.css';
import { API_BASE, API_HEADERS } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';


export default function LoginPage() {
    const router = useRouter();
    const { login } = useAuth();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            const res = await fetch(`${API_BASE}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...API_HEADERS },
                body: JSON.stringify({ email, password }),
            });

            if (!res.ok) {
                setError('Invalid email or password');
                setLoading(false);
                return;
            }

            // The backend now returns { access_token, token_type, user }
            const data = await res.json();
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
            <h1 className={styles.title}>Welcome to Grid-X</h1>
            <p className={styles.subtitle}>The Decentralized Resource Mesh</p>

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
                </div>

                {error && <p className={styles.error}>{error}</p>}

                <button type="submit" className={styles.primaryBtn} disabled={loading}>
                    {loading ? 'Authenticating…' : 'Authenticate'}
                </button>

                <div className={styles.infoContainer}>
                    <div className={styles.infoIcon}>i</div>
                    <span className={styles.tooltip}>Authentication handled by Grid-X backend</span>
                </div>

                <p className={styles.register}>
                    New to Grid-X ? {' '}
                    <span onClick={() => router.push('/registration')}>
                        Create an account
                    </span>
                </p>

            </form>

        </div>
    );
}
