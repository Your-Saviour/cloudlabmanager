import { useState } from 'react'
import { ChevronDown, ChevronRight, Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'

interface ConnectionGuideProps {
  guide: {
    ssh: string | null
    web_url: string | null
    fqdn: string | null
  }
  serviceName: string
}

function CopyButton({ text }: { text: string }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      className="h-6 w-6 shrink-0"
      onClick={() => {
        navigator.clipboard.writeText(text)
        toast.success('Copied')
      }}
      aria-label="Copy to clipboard"
    >
      <Copy className="h-3 w-3" />
    </Button>
  )
}

export function ConnectionGuide({ guide, serviceName }: ConnectionGuideProps) {
  const [expanded, setExpanded] = useState(false)

  const hasContent = guide.ssh || guide.web_url || guide.fqdn
  if (!hasContent) return null

  return (
    <div className="border-t border-border/30 pt-3 mt-3">
      <button
        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground w-full transition-colors"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-label={`Connection guide for ${serviceName}`}
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4 shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0" />
        )}
        <span>Connection Guide</span>
      </button>
      {expanded && (
        <div className="mt-3 space-y-3 text-sm animate-slide-down">
          {guide.ssh && (
            <div>
              <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
                SSH
              </span>
              <div className="flex items-center gap-2 mt-1">
                <code className="bg-muted/50 rounded px-3 py-1.5 font-mono text-xs flex-1 truncate">
                  {guide.ssh}
                </code>
                <CopyButton text={guide.ssh} />
              </div>
            </div>
          )}
          {guide.web_url && (
            <div>
              <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
                Web URL
              </span>
              <div className="flex items-center gap-2 mt-1">
                <a
                  href={guide.web_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-xs text-primary hover:underline truncate"
                >
                  {guide.web_url}
                </a>
                <CopyButton text={guide.web_url} />
              </div>
            </div>
          )}
          {guide.fqdn && (
            <div>
              <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
                FQDN
              </span>
              <div className="font-mono text-xs mt-1">{guide.fqdn}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
