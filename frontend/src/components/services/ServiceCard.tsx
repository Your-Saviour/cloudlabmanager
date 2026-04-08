import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Square,
  Settings,
  Terminal,
  ChevronDown,
  ChevronUp,
  Star,
  Copy,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { toast } from 'sonner'
import { ScriptRunner } from './ScriptRunner'
import { ServiceOutputsPanel } from './ServiceOutputsPanel'
import { ServiceCrossLinks } from './ServiceCrossLinks'
import type { ServiceSummary } from './ServiceCrossLinks'
import type { InventoryObject, ServiceScript } from '@/types'

interface ServiceCardProps {
  obj: InventoryObject
  index: number
  scripts: ServiceScript[]
  summary?: ServiceSummary
  isSelected: boolean
  isPinned: boolean
  isExpanded: boolean
  canDeploy: boolean
  canStop: boolean
  canConfig: boolean
  canFiles: boolean
  isPending: boolean
  isStopPending: boolean
  onToggleSelect: () => void
  onTogglePin: () => void
  onToggleExpand: () => void
  onRunScript: (script: ServiceScript) => void
  onStop: () => void
}

export function ServiceCard({
  obj,
  index,
  scripts,
  summary,
  isSelected,
  isPinned,
  isExpanded,
  canDeploy,
  canStop,
  canConfig,
  canFiles,
  isPending,
  isStopPending,
  onToggleSelect,
  onTogglePin,
  onToggleExpand,
  onRunScript,
  onStop,
}: ServiceCardProps) {
  const navigate = useNavigate()
  const [ipHovered, setIpHovered] = useState(false)

  const name = (obj.data.name as string) || obj.name
  const powerStatus = obj.data.power_status as string | undefined
  const isRunning = powerStatus === 'running'
  const isSuspended = powerStatus === 'suspended'
  const tags = obj.tags || []

  const copyIp = () => {
    if (obj.data.ip) {
      navigator.clipboard.writeText(String(obj.data.ip))
      toast.success('IP copied')
    }
  }

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-xl border border-border/50',
        'bg-card hover:border-border hover:shadow-xl hover:shadow-primary/5 hover:-translate-y-0.5',
        'transition-all duration-300 animate-card-in flex flex-col',
        isRunning && 'border-l-2 border-l-emerald-500/40',
      )}
      style={{ animationDelay: `${index * 60}ms` }}
    >
      {/* Status Strip */}
      <div
        className={cn(
          'absolute top-0 left-0 right-0 h-1',
          isRunning ? 'status-strip-running glow-emerald' : isSuspended ? 'bg-amber-500' : 'bg-zinc-600',
        )}
      />

      {/* Header Row */}
      <div className="flex items-center gap-3 p-5 pb-0">
        <Checkbox
          checked={isSelected}
          onCheckedChange={onToggleSelect}
          aria-label={`Select ${name}`}
        />
        <h3 className="font-display text-lg font-semibold min-w-0 truncate">{name}</h3>
        <span className="flex items-center gap-1.5 ml-1 shrink-0">
          <span
            className={cn(
              'h-2 w-2 rounded-full',
              isRunning ? 'bg-emerald-500 animate-status-pulse' : isSuspended ? 'bg-amber-500' : 'bg-zinc-600',
            )}
          />
          <span
            className={cn(
              'text-xs font-medium',
              isRunning ? 'text-emerald-400' : isSuspended ? 'text-amber-400' : 'text-zinc-500',
            )}
          >
            {powerStatus ? powerStatus.charAt(0).toUpperCase() + powerStatus.slice(1) : 'Unknown'}
          </span>
        </span>
        <div className="flex items-center gap-1 ml-auto shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              'h-7 w-7',
              isPinned ? 'text-amber-400 hover:text-amber-300' : 'text-muted-foreground hover:text-amber-400',
            )}
            onClick={(e) => { e.stopPropagation(); onTogglePin() }}
            title={isPinned ? 'Unpin from dashboard' : 'Pin to dashboard'}
            aria-label={isPinned ? `Unpin ${name}` : `Pin ${name}`}
          >
            <Star className={cn('h-4 w-4', isPinned && 'fill-current')} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground"
            onClick={onToggleExpand}
          >
            {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {/* Tags + Cross-links */}
      <div className="px-5 pt-2">
        {tags.length > 0 && (
          <div className="flex gap-1.5 flex-wrap">
            {tags.map((t) => (
              <Badge
                key={t.id}
                variant="outline"
                className="text-[11px] px-2 py-0.5"
                style={{ borderColor: t.color, color: t.color }}
              >
                {t.name}
              </Badge>
            ))}
          </div>
        )}
        <ServiceCrossLinks serviceName={name} summary={summary} />
      </div>

      {/* Data Cells */}
      <div className="flex gap-3 px-5 pt-3 pb-1">
        {obj.data.hostname && (
          <div className="bg-background/50 rounded-lg px-3 py-2.5 flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">Hostname</div>
            <div className="text-sm text-foreground truncate mt-0.5">{String(obj.data.hostname)}</div>
          </div>
        )}
        {obj.data.ip && (
          <div
            className="bg-background/50 rounded-lg px-3 py-2.5 flex-1 min-w-0 relative group/ip cursor-pointer"
            onMouseEnter={() => setIpHovered(true)}
            onMouseLeave={() => setIpHovered(false)}
            onClick={copyIp}
            title="Click to copy IP"
          >
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">IP Address</div>
            <div className="text-sm font-mono text-foreground truncate mt-0.5 flex items-center gap-1.5">
              {String(obj.data.ip)}
              <Copy className={cn('h-3 w-3 text-muted-foreground transition-opacity', ipHovered ? 'opacity-100' : 'opacity-0')} />
            </div>
          </div>
        )}
        {obj.data.region && (
          <div className="bg-background/50 rounded-lg px-3 py-2.5 flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">Region</div>
            <div className="text-sm text-foreground truncate mt-0.5">{String(obj.data.region)}</div>
          </div>
        )}
      </div>

      {/* Outputs Panel */}
      {isExpanded && (
        <div className="px-5 pt-2">
          <ServiceOutputsPanel serviceName={name} />
        </div>
      )}

      {/* Actions Footer */}
      <div className="flex items-center justify-between border-t border-border/50 pt-4 pb-5 px-5 mt-auto">
        <div className="flex items-center gap-2">
          {canDeploy && scripts.length > 0 && (
            <ScriptRunner
              scripts={scripts}
              onRun={onRunScript}
              disabled={isPending}
            />
          )}
          {canStop && isRunning && (
            <Button
              variant="outline"
              size="sm"
              className="border-destructive/40 text-destructive hover:bg-destructive/10"
              onClick={onStop}
              disabled={isStopPending}
            >
              <Square className="mr-1 h-3 w-3" /> Stop
            </Button>
          )}
        </div>
        <div className="flex items-center gap-1">
          {(canConfig || canFiles) && (
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              title="Config & Files"
              onClick={() => navigate(`/services/${name}/config`)}
            >
              <Settings className="h-4 w-4" />
            </Button>
          )}
          {isRunning && obj.data.ip && obj.data.hostname && (
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              title="SSH"
              onClick={() => navigate(`/ssh/${obj.data.hostname}/${obj.data.ip}`)}
            >
              <Terminal className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
