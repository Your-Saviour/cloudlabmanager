import { useState } from 'react'
import { Eye, EyeOff, Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

interface CredentialDisplayProps {
  value: string
  username?: string
}

export function CredentialDisplay({ value, username }: CredentialDisplayProps) {
  const [revealed, setRevealed] = useState(false)

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
        onClick={() => setRevealed(!revealed)}
        aria-label={revealed ? 'Hide credential' : 'Reveal credential'}
      >
        {revealed ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6"
        onClick={() => {
          navigator.clipboard.writeText(value)
          toast.success('Copied')
        }}
        aria-label="Copy to clipboard"
      >
        <Copy className="h-3 w-3" />
      </Button>
    </div>
  )
}
