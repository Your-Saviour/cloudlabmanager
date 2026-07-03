import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Hexagon } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import api from '@/lib/api'

/**
 * Landing page for the OIDC redirect. The backend redirects here with the CLM
 * internal JWT in the URL fragment (#token=...). We read it, fetch the current
 * user, persist both to the auth store (localStorage), and continue into the app
 * — the same bearer-token model used by local login.
 */
export default function OidcCallback() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const [error, setError] = useState('')
  const ran = useRef(false)

  useEffect(() => {
    if (ran.current) return
    ran.current = true

    const params = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    const token = params.get('token')
    // Strip the token from the URL history immediately.
    window.history.replaceState(null, '', window.location.pathname)

    if (!token) {
      setError('Sign-in failed: missing token')
      setTimeout(() => navigate('/login?oidc_error=missing_token'), 1500)
      return
    }

    ;(async () => {
      try {
        const { data } = await api.get('/api/auth/me', {
          headers: { Authorization: `Bearer ${token}` },
        })
        const u = data.user || data
        setAuth(token, {
          id: u.id,
          username: u.username,
          display_name: u.display_name,
          email: u.email,
          permissions: u.permissions || data.permissions || [],
        })
        navigate('/dashboard')
      } catch {
        setError('Sign-in failed')
        setTimeout(() => navigate('/login?oidc_error=profile_failed'), 1500)
      }
    })()
  }, [navigate, setAuth])

  return (
    <div className="min-h-screen flex flex-col items-center justify-center login-gradient-bg p-4 gap-4">
      <Hexagon className="h-10 w-10 text-primary animate-icon-pulse" />
      <p className="text-sm text-muted-foreground">
        {error || 'Signing you in…'}
      </p>
    </div>
  )
}
