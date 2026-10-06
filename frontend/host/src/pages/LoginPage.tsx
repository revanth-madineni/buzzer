import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../lib/api';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent, CardHeader } from '../components/ui/card';
import { ThemeToggle } from '../components/ThemeToggle';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // Handle return from OAuth2 — exchange temp token for full access token
  useEffect(() => {
    if (searchParams.get('from') !== 'oauth2') return;

    const oauthError = searchParams.get('error');
    if (oauthError) {
      setError(oauthError);
      return;
    }

    const match = window.location.hash.match(/oauth2_data=([^&]+)/);
    if (!match) return;

    let tempToken: string;
    try {
      const data = JSON.parse(decodeURIComponent(match[1]));
      tempToken = data.temp_token;
      if (!tempToken) throw new Error();
    } catch {
      setError('Invalid authentication response');
      return;
    }

    setLoading(true);
    fetch('/api/auth/exchange-temp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tempToken}` },
    })
      .then(res => res.ok ? res.json() : res.json().then((e: { detail?: string }) => Promise.reject(e.detail ?? 'Sign-in failed')))
      .then((data: { access_token: string }) => {
        localStorage.setItem('token', data.access_token);
        window.history.replaceState(null, '', window.location.pathname);
        navigate('/home');
      })
      .catch((msg: unknown) => {
        setError(typeof msg === 'string' ? msg : 'Sign-in failed');
        setLoading(false);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const data = await api.post<{ access_token: string }>('/auth/login', { username, password });
      localStorage.setItem('token', data.access_token);
      navigate('/home');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <ThemeToggle className="fixed top-4 right-4 z-40" />
      <Card className="w-full max-w-md">
        <CardHeader>
          <h1 className="text-2xl font-bold text-slate-100">Buzzer</h1>
          <p className="text-slate-400 text-sm mt-1">Host Sign In</p>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Primary: UW NetID SSO */}
          <a
            href="/api/auth/oauth2-callback?redirect_to=/host/login"
            className={`flex items-center justify-center w-full py-2.5 px-4 rounded-lg font-medium transition-colors
              ${loading
                ? 'bg-slate-700 text-slate-500 pointer-events-none'
                : 'bg-indigo-600 hover:bg-indigo-500 text-white'
              }`}
          >
            Sign in with UW NetID
          </a>

          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-slate-700" />
            <span className="text-slate-500 text-xs">or local account</span>
            <div className="flex-1 h-px bg-slate-700" />
          </div>

          {/* Secondary: username/password for admin & local accounts */}
          <form onSubmit={handleSubmit} className="space-y-3">
            <Input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="Username"
              autoComplete="username"
              required
            />
            <Input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Password"
              autoComplete="current-password"
              required
            />
            {error && <p className="text-red-400 text-sm">{error}</p>}
            <Button type="submit" variant="outline" className="w-full" disabled={loading}>
              {loading ? 'Signing in…' : 'Sign In'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
