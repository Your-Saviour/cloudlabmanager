import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Hexagon, ShieldCheck, KeyRound } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { useAuthStatus } from '@/hooks/useAuth'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const setAuth = useAuthStore((s) => s.setAuth)
  const navigate = useNavigate()
  const { data: status } = useAuthStatus()

  // Surface an OIDC error passed back via ?oidc_error=...
  useEffect(() => {
    const oidcError = new URLSearchParams(window.location.search).get('oidc_error')
    if (oidcError) setError(`SSO sign-in failed (${oidcError})`)
  }, [])

  // MFA state
  const [mfaRequired, setMfaRequired] = useState(false)
  const [mfaToken, setMfaToken] = useState('')
  const [mfaCode, setMfaCode] = useState('')

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await api.post('/api/auth/login', { username, password })

      if (data.mfa_required) {
        // MFA is enabled — show TOTP input
        setMfaRequired(true)
        setMfaToken(data.mfa_token)
        setLoading(false)
        return
      }

      // No MFA — proceed directly
      const u = data.user || data
      setAuth(data.access_token, {
        id: u.id,
        username: u.username,
        display_name: u.display_name,
        email: u.email,
        permissions: u.permissions || data.permissions || [],
      })
      navigate('/dashboard')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  const handleMfaVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await api.post('/api/auth/mfa/verify', {
        mfa_token: mfaToken,
        code: mfaCode,
      })
      const u = data.user || data
      setAuth(data.access_token, {
        id: u.id,
        username: u.username,
        display_name: u.display_name,
        email: u.email,
        permissions: u.permissions || data.permissions || [],
      })
      navigate('/dashboard')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Verification failed')
    } finally {
      setLoading(false)
    }
  }

  const handleBackToLogin = () => {
    setMfaRequired(false)
    setMfaToken('')
    setMfaCode('')
    setError('')
    setPassword('')
  }

  // MFA Verification Step
  if (mfaRequired) {
    return (
      <div className="min-h-screen flex items-center justify-center login-gradient-bg p-4">
        <Card className="w-full max-w-sm bg-card/80 backdrop-blur-xl border-border/50">
          <CardHeader className="text-center">
            <div className="flex justify-center mb-4">
              <ShieldCheck className="h-10 w-10 text-primary animate-icon-pulse" />
            </div>
            <CardTitle className="text-xl">Two-Factor Authentication</CardTitle>
            <CardDescription>
              Enter the 6-digit code from your authenticator app, or use a backup code
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleMfaVerify} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="mfa-code">Verification Code</Label>
                <Input
                  id="mfa-code"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value)}
                  placeholder="000000"
                  required
                  autoFocus
                  autoComplete="one-time-code"
                  className="text-center text-lg tracking-widest"
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? 'Verifying...' : 'Verify'}
              </Button>
              <div className="text-center">
                <button
                  type="button"
                  onClick={handleBackToLogin}
                  className="text-sm text-muted-foreground hover:text-primary transition-colors"
                >
                  Back to login
                </button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Login Step
  return (
    <div className="min-h-screen flex items-center justify-center login-gradient-bg p-4">
      <Card className="w-full max-w-sm bg-card/80 backdrop-blur-xl border-border/50">
        <CardHeader className="text-center">
          <div className="flex justify-center mb-4">
            <Hexagon className="h-10 w-10 text-primary animate-icon-pulse" />
          </div>
          <CardTitle className="text-xl">Welcome back</CardTitle>
          <CardDescription>Sign in to CloudLab Manager</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? 'Signing in...' : 'Sign In'}
            </Button>
            {status?.oidc_enabled && (
              <>
                <div className="relative py-1">
                  <div className="absolute inset-0 flex items-center">
                    <span className="w-full border-t border-border/50" />
                  </div>
                  <div className="relative flex justify-center text-xs uppercase">
                    <span className="bg-card px-2 text-muted-foreground">or</span>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={() => { window.location.href = '/api/auth/oidc/login' }}
                >
                  <KeyRound className="mr-2 h-4 w-4" />
                  Sign in with {status.oidc_provider || 'SSO'}
                </Button>
              </>
            )}
            <div className="text-center">
              <Link to="/forgot-password" className="text-sm text-muted-foreground hover:text-primary transition-colors">
                Forgot password?
              </Link>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
