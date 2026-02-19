import { useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { Eye, EyeOff, Copy, CheckCircle, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import api from '@/lib/api'

interface CredentialDisplayProps {
  value: string
  username?: string
  credentialId?: number
  credentialName?: string
  source?: 'portal' | 'inventory'
  requirePersonalKey?: boolean
  userHasPersonalKey?: boolean
}

export function CredentialDisplay({ value, username, credentialId, credentialName, source, requirePersonalKey, userHasPersonalKey }: CredentialDisplayProps) {
  const [revealed, setRevealed] = useState(false)

  if (requirePersonalKey) {
    return (
      <div className="flex items-center gap-2 text-sm">
        {userHasPersonalKey ? (
          <>
            <CheckCircle className="h-4 w-4 text-green-500" />
            <span className="text-muted-foreground">
              Use your personal SSH key to connect
            </span>
          </>
        ) : (
          <>
            <AlertCircle className="h-4 w-4 text-amber-500" />
            <span className="text-muted-foreground">
              Personal SSH key required &mdash;{' '}
              <RouterLink to="/profile" className="underline hover:text-foreground transition-colors">upload in your profile</RouterLink>
            </span>
          </>
        )}
      </div>
    )
  }

  const handleReveal = () => {
    if (!revealed && credentialId) {
      api.post('/api/credentials/audit', {
        credential_id: credentialId,
        credential_name: credentialName || 'Unknown',
        action: 'viewed',
        source: source || 'portal',
      }).catch(() => {})
    }
    setRevealed(!revealed)
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(value)
    if (credentialId) {
      api.post('/api/credentials/audit', {
        credential_id: credentialId,
        credential_name: credentialName || 'Unknown',
        action: 'copied',
        source: source || 'portal',
      }).catch(() => {})
    }
    toast.success('Copied')
  }

  return (
    <div className="flex items-center gap-2">
      {username && (
        <span className="text-xs text-muted-foreground font-mono">{username}</span>
      )}
      <span
        className={cn(
          'font-mono text-xs bg-muted/50 rounded-md px-3 py-1.5',
          !revealed && 'blur-sm select-none'
        )}
      >
        {value}
      </span>
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6"
        onClick={handleReveal}
        aria-label={revealed ? 'Hide credential' : 'Reveal credential'}
      >
        {revealed ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6"
        onClick={handleCopy}
        aria-label="Copy to clipboard"
      >
        <Copy className="h-3 w-3" />
      </Button>
    </div>
  )
}
