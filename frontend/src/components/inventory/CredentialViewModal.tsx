import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { toast } from 'sonner'

interface CredentialViewModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  name: string
  value: string
  loading?: boolean
}

export function CredentialViewModal({ open, onOpenChange, name, value, loading }: CredentialViewModalProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      toast.success('Copied')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error('Failed to copy to clipboard')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{name}</DialogTitle>
        </DialogHeader>
        <div className="relative">
          {loading ? (
            <div className="bg-muted rounded-md p-4 h-32 flex items-center justify-center">
              <span className="text-sm text-muted-foreground animate-pulse">Loading...</span>
            </div>
          ) : (
            <pre className="bg-muted rounded-md p-4 text-xs font-mono whitespace-pre-wrap break-all max-h-96 overflow-auto">
              {value}
            </pre>
          )}
          {!loading && value && (
            <Button
              variant="outline"
              size="sm"
              className="absolute top-2 right-2"
              onClick={handleCopy}
              aria-label={copied ? 'Copied to clipboard' : 'Copy to clipboard'}
            >
              {copied ? <Check className="h-3 w-3 mr-1" /> : <Copy className="h-3 w-3 mr-1" />}
              {copied ? 'Copied' : 'Copy'}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
