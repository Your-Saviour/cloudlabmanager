import { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { toast } from 'sonner'
import api from '@/lib/api'

interface ReauthDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onVerified: () => void
}

export function ReauthDialog({ open, onOpenChange, onVerified }: ReauthDialogProps) {
  const [password, setPassword] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [mfaEnabled, setMfaEnabled] = useState<boolean | null>(null)

  // Check MFA status when dialog opens
  const handleOpenChange = async (isOpen: boolean) => {
    if (isOpen && mfaEnabled === null) {
      try {
        const { data } = await api.get('/api/auth/mfa/status')
        setMfaEnabled(data.mfa_enabled)
      } catch {
        setMfaEnabled(false)
      }
    }
    if (!isOpen) {
      setPassword('')
      setMfaCode('')
    }
    onOpenChange(isOpen)
  }

  const handleSubmit = async () => {
    setLoading(true)
    try {
      await api.post('/api/auth/verify-identity', {
        password: password || undefined,
        mfa_code: mfaCode || undefined,
      })
      setPassword('')
      setMfaCode('')
      onOpenChange(false)
      onVerified()
    } catch {
      toast.error('Verification failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" /> Confirm Identity
          </DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          Re-authenticate to view credential values.
        </p>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Password</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              autoFocus
            />
          </div>
          {mfaEnabled && (
            <div className="space-y-2">
              <Label>MFA Code (alternative)</Label>
              <Input
                type="text"
                inputMode="numeric"
                maxLength={6}
                placeholder="6-digit code"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={loading || (!password && !mfaCode)}>
            {loading ? 'Verifying...' : 'Verify'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
