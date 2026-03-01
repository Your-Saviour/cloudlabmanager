import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Hexagon, AlertCircle } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

interface LinkInfo {
  label: string
  roles: { id: number; name: string }[]
  expires_at: string | null
}

export default function JoinPage() {
  const { token } = useParams<{ token: string }>()
  const [linkInfo, setLinkInfo] = useState<LinkInfo | null>(null)
  const [linkError, setLinkError] = useState('')
  const [infoLoading, setInfoLoading] = useState(true)
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const setAuth = useAuthStore((s) => s.setAuth)
  const navigate = useNavigate()

  useEffect(() => {
    if (!token) return
    api.get(`/api/auth/join/${token}/info`)
      .then(({ data }) => {
        setLinkInfo(data)
        setInfoLoading(false)
      })
      .catch((err) => {
        setLinkError(err.response?.data?.detail || 'This invite link is invalid or has expired')
        setInfoLoading(false)
      })
  }, [token])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await api.post('/api/auth/join', {
        token,
        username,
        email,
        password,
        display_name: displayName || undefined,
      })
      const u = data.user || data
      setAuth(data.access_token, {
        id: u.id,
        username: u.username,
        display_name: u.display_name,
        email: u.email || '',
        permissions: u.permissions || data.permissions || [],
      })
      navigate('/dashboard')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create account')
    } finally {
      setLoading(false)
    }
  }

  if (infoLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-sm">
          <CardHeader className="text-center">
            <div className="flex justify-center mb-4"><Hexagon className="h-10 w-10 text-primary" /></div>
            <Skeleton className="h-6 w-48 mx-auto" />
            <Skeleton className="h-4 w-32 mx-auto mt-2" />
          </CardHeader>
          <CardContent className="space-y-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </CardContent>
        </Card>
      </div>
    )
  }

  if (linkError) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-sm">
          <CardHeader className="text-center">
            <div className="flex justify-center mb-4"><AlertCircle className="h-10 w-10 text-destructive" /></div>
            <CardTitle className="text-xl">Invalid Link</CardTitle>
            <CardDescription>{linkError}</CardDescription>
          </CardHeader>
          <CardContent className="text-center">
            <Button variant="outline" onClick={() => navigate('/login')}>Go to Login</Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="flex justify-center mb-4"><Hexagon className="h-10 w-10 text-primary" /></div>
          <CardTitle className="text-xl">Join {linkInfo?.label}</CardTitle>
          <CardDescription>Create your account</CardDescription>
          {linkInfo?.roles && linkInfo.roles.length > 0 && (
            <div className="flex justify-center gap-1 mt-2">
              {linkInfo.roles.map((r) => (
                <Badge key={r.id} variant="outline" className="text-xs">{r.name}</Badge>
              ))}
            </div>
          )}
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="displayName">Display Name</Label>
              <Input id="displayName" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? 'Creating...' : 'Create Account'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
