import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Hexagon } from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api.post('/api/auth/forgot-password', { email })
      setSent(true)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to send reset email')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="flex justify-center mb-4"><Hexagon className="h-10 w-10 text-primary" /></div>
          <CardTitle className="text-xl">Forgot Password</CardTitle>
          <CardDescription>{sent ? 'Check your email for a reset link.' : 'Enter your email to receive a reset link.'}</CardDescription>
        </CardHeader>
        <CardContent>
          {!sent ? (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading}>{loading ? 'Sending...' : 'Send Reset Link'}</Button>
              <div className="text-center">
                <Link to="/login" className="text-sm text-muted-foreground hover:text-primary">Back to Login</Link>
              </div>
            </form>
          ) : (
            <div className="text-center">
              <Link to="/login" className="text-sm text-primary hover:underline">Back to Login</Link>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
