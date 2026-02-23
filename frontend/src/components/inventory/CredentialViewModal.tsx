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
  publicKey?: string
  loading?: boolean
}

export function CredentialViewModal({ open, onOpenChange, name, value, publicKey, loading }: CredentialViewModalProps) {
  const [copiedField, setCopiedField] = useState<string | null>(null)

  const handleCopy = async (text: string, field: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedField(field)
      toast.success('Copied')
      setTimeout(() => setCopiedField(null), 2000)
    } catch {
      toast.error('Failed to copy to clipboard')
    }
  }

  const hasPublicKey = !!publicKey

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{name}</DialogTitle>
        </DialogHeader>
        {loading ? (
          <div className="bg-muted rounded-md p-4 h-32 flex items-center justify-center">
            <span className="text-sm text-muted-foreground animate-pulse">Loading...</span>
          </div>
        ) : (
          <div className="space-y-4">
            {value && (
              <div>
                {hasPublicKey && (
                  <div className="text-xs font-medium text-muted-foreground mb-1">Private Key</div>
                )}
                <div className="relative">
                  <pre className="bg-muted rounded-md p-4 text-xs font-mono whitespace-pre-wrap break-all max-h-64 overflow-auto">
                    {value}
                  </pre>
                  <Button
                    variant="outline"
                    size="sm"
                    className="absolute top-2 right-2"
                    onClick={() => handleCopy(value, 'private')}
                    aria-label={copiedField === 'private' ? 'Copied to clipboard' : 'Copy to clipboard'}
                  >
                    {copiedField === 'private' ? <Check className="h-3 w-3 mr-1" /> : <Copy className="h-3 w-3 mr-1" />}
                    {copiedField === 'private' ? 'Copied' : 'Copy'}
                  </Button>
                </div>
              </div>
            )}
            {publicKey && (
              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1">Public Key</div>
                <div className="relative">
                  <pre className="bg-muted rounded-md p-4 text-xs font-mono whitespace-pre-wrap break-all max-h-40 overflow-auto">
                    {publicKey}
                  </pre>
                  <Button
                    variant="outline"
                    size="sm"
                    className="absolute top-2 right-2"
                    onClick={() => handleCopy(publicKey, 'public')}
                    aria-label={copiedField === 'public' ? 'Copied to clipboard' : 'Copy to clipboard'}
                  >
                    {copiedField === 'public' ? <Check className="h-3 w-3 mr-1" /> : <Copy className="h-3 w-3 mr-1" />}
                    {copiedField === 'public' ? 'Copied' : 'Copy'}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
