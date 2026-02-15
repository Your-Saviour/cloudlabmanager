import { useState } from 'react'
import {
  ExternalLink,
  Globe,
  Link,
  Terminal,
  Copy,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useHasPermission } from '@/lib/permissions'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { toast } from 'sonner'
import { CredentialDisplay } from './CredentialDisplay'
import { ConnectionGuide } from './ConnectionGuide'
import { BookmarkSection } from './BookmarkSection'
import { SSHTerminalModal } from './SSHTerminalModal'
import type { PortalService } from '@/types/portal'

function HealthBadge({ status }: { status: string }) {
  const config: Record<string, { color: string; label: string }> = {
    healthy: { color: 'text-emerald-400', label: 'Healthy' },
    unhealthy: { color: 'text-red-400', label: 'Unhealthy' },
    degraded: { color: 'text-amber-400', label: 'Degraded' },
    unknown: { color: 'text-zinc-400', label: 'Unknown' },
  }
  const c = config[status] || config.unknown
  return (
    <span className={cn('flex items-center gap-1.5 text-xs font-medium', c.color)}>
      <span
        className={cn(
          'h-2 w-2 rounded-full',
          status === 'healthy' && 'bg-emerald-500',
          status === 'unhealthy' && 'bg-red-500',
          status === 'degraded' && 'bg-amber-500',
          (status === 'unknown' || !config[status]) && 'bg-zinc-500'
        )}
      />
      {c.label}
    </span>
  )
}

interface ServicePortalCardProps {
  service: PortalService
  index: number
}

export function ServicePortalCard({ service, index }: ServicePortalCardProps) {
  const isRunning = service.power_status === 'running'
  const isSuspended = service.power_status === 'suspended'
  const canEditBookmarks = useHasPermission('portal.bookmarks.edit')
  const [sshOpen, setSshOpen] = useState(false)

  const primaryUrl = service.outputs.find((o) => o.type === 'url')?.value
  const urlOutputs = service.outputs.filter((o) => o.type === 'url')
  const credentialOutputs = service.outputs.filter((o) => o.type === 'credential')
  const otherOutputs = service.outputs.filter(
    (o) => o.type !== 'url' && o.type !== 'credential'
  )
  const hasOutputs = service.outputs.length > 0

  return (
    <div
      className="relative overflow-hidden rounded-xl border border-border/50 bg-card p-6 hover:border-border hover:shadow-lg hover:shadow-primary/5 transition-all duration-300 animate-card-in flex flex-col"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      {/* Status Strip */}
      <div
        className={cn(
          'absolute top-0 left-0 right-0 h-[3px]',
          isRunning
            ? 'bg-emerald-500 glow-emerald'
            : isSuspended
              ? 'bg-amber-500'
              : 'bg-zinc-600'
        )}
      />

      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-display text-lg font-semibold">{service.display_name}</h3>
          {service.health ? (
            <HealthBadge status={service.health.overall_status} />
          ) : (
            <HealthBadge status="unknown" />
          )}
        </div>
        <span
          className={cn(
            'text-xs font-medium capitalize',
            isRunning
              ? 'text-emerald-400'
              : isSuspended
                ? 'text-amber-400'
                : 'text-zinc-500'
          )}
        >
          {service.power_status || 'Unknown'}
        </span>
      </div>

      {/* FQDN + Open in Browser */}
      {service.fqdn && (
        <div className="flex items-center gap-2 mb-4">
          <a
            href={primaryUrl || `https://${service.fqdn}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-3 py-2 bg-primary/5 border border-primary/20 rounded-lg hover:bg-primary/10 transition-colors group flex-1 min-w-0"
          >
            <Globe className="h-3.5 w-3.5 text-primary shrink-0" />
            <span className="text-sm font-mono text-primary truncate">
              {service.fqdn}
            </span>
            <ExternalLink className="h-3 w-3 text-primary/60 group-hover:text-primary shrink-0 ml-auto" />
          </a>
          {primaryUrl && (
            <a href={primaryUrl} target="_blank" rel="noopener noreferrer">
              <Button variant="outline" size="sm">
                <ExternalLink className="mr-1.5 h-3.5 w-3.5" /> Open
              </Button>
            </a>
          )}
        </div>
      )}

      {/* Open in Browser (no FQDN but has URL) */}
      {!service.fqdn && primaryUrl && (
        <div className="mb-4">
          <a href={primaryUrl} target="_blank" rel="noopener noreferrer">
            <Button variant="outline" size="sm" className="w-full">
              <ExternalLink className="mr-1.5 h-3.5 w-3.5" /> Open in Browser
            </Button>
          </a>
        </div>
      )}

      {/* Data Cells */}
      <div className="flex gap-3 mb-4">
        {service.hostname && (
          <div className="bg-background/50 rounded-lg px-3 py-2.5 flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">
              Hostname
            </div>
            <div className="text-sm text-foreground truncate mt-0.5">
              {service.hostname}
            </div>
          </div>
        )}
        {service.ip && (
          <div className="bg-background/50 rounded-lg px-3 py-2.5 flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">
              IP
            </div>
            <div className="text-sm font-mono text-foreground truncate mt-0.5">
              {service.ip}
            </div>
          </div>
        )}
        {service.region && (
          <div className="bg-background/50 rounded-lg px-3 py-2.5 flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">
              Region
            </div>
            <div className="text-sm text-foreground truncate mt-0.5">
              {service.region}
            </div>
          </div>
        )}
      </div>

      {/* Tags */}
      {service.tags.length > 0 && (
        <div className="flex gap-1.5 flex-wrap mb-4">
          {service.tags.map((tag) => (
            <Badge key={tag} variant="outline" className="text-[11px] px-2 py-0.5">
              {tag}
            </Badge>
          ))}
        </div>
      )}

      {/* Outputs Section */}
      {hasOutputs && (
        <div className="border-t border-border/30 pt-3 mt-1 mb-3 space-y-3">
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">
            Outputs
          </span>

          {/* URL outputs */}
          {urlOutputs.map((out, i) => (
            <div
              key={`url-${i}`}
              className="flex items-center gap-2 hover:bg-muted/20 -mx-2 px-2 py-1 rounded-md transition-colors"
            >
              <Link className="h-3.5 w-3.5 text-primary shrink-0" />
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                {out.label}
              </span>
              <a
                href={out.value}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-xs text-primary hover:underline flex items-center gap-1 min-w-0 truncate ml-auto"
              >
                {out.value}
                <ExternalLink className="h-3 w-3 shrink-0" />
              </a>
            </div>
          ))}

          {/* Credential outputs */}
          {credentialOutputs.map((out, i) => (
            <div key={`cred-${i}`} className="space-y-1.5">
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                {out.label}
              </span>
              <CredentialDisplay value={out.value} username={out.username} />
            </div>
          ))}

          {/* Other outputs */}
          {otherOutputs.map((out, i) => (
            <div key={`other-${i}`} className="text-xs">
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                {out.label}
              </span>{' '}
              <span className="text-foreground">{out.value || '-'}</span>
            </div>
          ))}
        </div>
      )}

      {/* No outputs */}
      {!hasOutputs && (
        <div className="border-t border-border/30 pt-3 mt-1 mb-3">
          <span className="text-xs text-muted-foreground">No outputs</span>
        </div>
      )}

      {/* Connection Guide */}
      <ConnectionGuide guide={service.connection_guide} serviceName={service.name} />

      {/* Bookmarks */}
      <BookmarkSection
        serviceName={service.name}
        bookmarks={service.bookmarks}
        canEdit={canEditBookmarks}
      />

      {/* Footer Actions */}
      <div className="border-t border-border/50 pt-4 mt-auto">
        <div className="flex items-center gap-2">
          {isRunning && service.ip && service.hostname && (
            <Button
              variant="ghost"
              size="sm"
              className="text-xs h-7"
              onClick={() => setSshOpen(true)}
              title="SSH Terminal"
              aria-label={`Open SSH terminal for ${service.display_name}`}
            >
              <Terminal className="mr-1.5 h-3.5 w-3.5" /> SSH
            </Button>
          )}
          {(primaryUrl || service.fqdn) && (
            <a
              href={primaryUrl || `https://${service.fqdn}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button variant="ghost" size="sm" className="text-xs h-7">
                <ExternalLink className="mr-1.5 h-3.5 w-3.5" /> Open
              </Button>
            </a>
          )}
          <span className="text-xs text-muted-foreground ml-auto capitalize">
            {service.plan}
          </span>
        </div>
      </div>

      {/* SSH Terminal Modal */}
      {service.hostname && service.ip && (
        <SSHTerminalModal
          open={sshOpen}
          onOpenChange={setSshOpen}
          hostname={service.hostname}
          ip={service.ip}
        />
      )}
    </div>
  )
}
