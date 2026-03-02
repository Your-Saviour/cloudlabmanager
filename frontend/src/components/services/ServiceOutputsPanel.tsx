import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Eye, EyeOff, Copy, ExternalLink } from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'

interface ServiceOutputsPanelProps {
  serviceName: string
}

export function ServiceOutputsPanel({ serviceName }: ServiceOutputsPanelProps) {
  const [revealedKeys, setRevealedKeys] = useState<Set<string>>(new Set())

  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['service-outputs', serviceName],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${serviceName}/outputs`)
      return (data.outputs || []) as { label: string; type: string; value: string; name?: string; username?: string }[]
    },
  })

  const toggleReveal = (key: string) => {
    setRevealedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    toast.success('Copied to clipboard')
  }

  if (isLoading) {
    return <div className="mb-4"><Skeleton className="h-16 w-full rounded-lg" /></div>
  }

  if (outputs.length === 0) {
    return (
      <div className="mb-4 text-xs text-muted-foreground text-center py-3 bg-background/60 rounded-lg border border-border/30">
        No outputs available
      </div>
    )
  }

  return (
    <div className="bg-background/60 rounded-lg border border-border/30 p-4 mb-4 animate-slide-down space-y-3">
      {outputs.map((out, i) => {
        const key = `${out.label}-${i}`

        if (out.type === 'url' && out.value) {
          return (
            <div key={key} className="flex items-center gap-2 group hover:bg-muted/20 -mx-2 px-2 py-1 rounded-md transition-colors">
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{out.label}</span>
              <a
                href={out.value}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-xs text-primary hover:underline flex items-center gap-1 min-w-0 truncate"
              >
                {out.value} <ExternalLink className="h-3 w-3 shrink-0" />
              </a>
            </div>
          )
        }

        if (out.type === 'credential') {
          const isRevealed = revealedKeys.has(key)
          return (
            <div key={key} className="space-y-1.5">
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{out.label}</span>
              <div className="flex items-center gap-2">
                <span
                  className={`font-mono text-xs bg-muted/50 rounded-md px-3 py-1.5 ${isRevealed ? '' : 'blur-sm select-none'}`}
                >
                  {out.value}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={() => toggleReveal(key)}
                >
                  {isRevealed ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={() => copyToClipboard(out.value)}
                >
                  <Copy className="h-3 w-3" />
                </Button>
              </div>
            </div>
          )
        }

        // Default: plain label: value
        return (
          <div key={key} className="text-xs">
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{out.label}</span>{' '}
            <span className="text-foreground">{out.value || '-'}</span>
          </div>
        )
      })}
    </div>
  )
}
