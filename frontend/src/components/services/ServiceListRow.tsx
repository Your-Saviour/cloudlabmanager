import { useNavigate } from 'react-router-dom'
import {
  Play,
  Square,
  Settings,
  Terminal,
  Star,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { ServiceSummary } from './ServiceCrossLinks'
import type { InventoryObject, ServiceScript } from '@/types'

interface ServiceListRowProps {
  obj: InventoryObject
  scripts: ServiceScript[]
  summary?: ServiceSummary
  isSelected: boolean
  isPinned: boolean
  canDeploy: boolean
  canStop: boolean
  canConfig: boolean
  canFiles: boolean
  isPending: boolean
  isStopPending: boolean
  onToggleSelect: () => void
  onTogglePin: () => void
  onRunScript: (script: ServiceScript) => void
  onStop: () => void
}

export function ServiceListRow({
  obj,
  scripts,
  summary,
  isSelected,
  isPinned,
  canDeploy,
  canStop,
  canConfig,
  canFiles,
  isPending,
  isStopPending,
  onToggleSelect,
  onTogglePin,
  onRunScript,
  onStop,
}: ServiceListRowProps) {
  const navigate = useNavigate()

  const name = (obj.data.name as string) || obj.name
  const powerStatus = obj.data.power_status as string | undefined
  const isRunning = powerStatus === 'running'
  const isSuspended = powerStatus === 'suspended'
  const tags = obj.tags || []

  const healthStatus = summary?.health_status
  const healthConfig: Record<string, { color: string; label: string }> = {
    healthy: { color: 'text-emerald-400', label: 'Healthy' },
    unhealthy: { color: 'text-red-400', label: 'Unhealthy' },
    degraded: { color: 'text-amber-400', label: 'Degraded' },
    unknown: { color: 'text-zinc-400', label: 'Unknown' },
  }
  const health = healthStatus ? healthConfig[healthStatus] || healthConfig.unknown : null

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border/50 bg-card px-4 py-3 hover:border-border transition-colors">
      <Checkbox
        checked={isSelected}
        onCheckedChange={onToggleSelect}
        aria-label={`Select ${name}`}
      />

      {/* Status dot */}
      <span
        className={cn(
          'h-2.5 w-2.5 rounded-full shrink-0',
          isRunning ? 'bg-emerald-500 animate-status-pulse' : isSuspended ? 'bg-amber-500' : 'bg-zinc-600',
        )}
        aria-label={isRunning ? 'Running' : isSuspended ? 'Suspended' : 'Stopped'}
      />

      {/* Name */}
      <span className="font-medium text-sm min-w-[140px] truncate">{name}</span>

      {/* Tags (max 2 + overflow) */}
      <div className="flex gap-1 min-w-[100px] max-w-[160px] shrink-0">
        {tags.slice(0, 2).map((t) => (
          <Badge
            key={t.id}
            variant="outline"
            className="text-[10px] px-1.5 py-0 truncate max-w-[70px]"
            style={{ borderColor: t.color, color: t.color }}
          >
            {t.name}
          </Badge>
        ))}
        {tags.length > 2 && (
          <Badge variant="outline" className="text-[10px] px-1.5 py-0">
            +{tags.length - 2}
          </Badge>
        )}
      </div>

      {/* Hostname */}
      <span className="text-sm font-mono text-muted-foreground truncate flex-1 min-w-0">
        {obj.data.hostname ? String(obj.data.hostname) : '-'}
      </span>

      {/* Region */}
      <span className="text-xs text-muted-foreground min-w-[50px] shrink-0">
        {obj.data.region ? String(obj.data.region) : '-'}
      </span>

      {/* Health chip */}
      <div className="min-w-[80px] shrink-0">
        {health ? (
          <span className={cn('flex items-center gap-1.5 text-xs font-medium', health.color)}>
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                healthStatus === 'healthy' && 'bg-emerald-500',
                healthStatus === 'unhealthy' && 'bg-red-500',
                healthStatus === 'degraded' && 'bg-amber-500',
                (healthStatus === 'unknown' || !healthConfig[healthStatus!]) && 'bg-zinc-500',
              )}
            />
            {health.label}
          </span>
        ) : (
          <span className="text-xs text-zinc-500">-</span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 shrink-0">
        {/* Script runner: icon button for single, dropdown for multi */}
        {canDeploy && scripts.length === 1 && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => onRunScript(scripts[0])}
            disabled={isPending}
            title={scripts[0].label}
          >
            <Play className="h-3.5 w-3.5" />
          </Button>
        )}
        {canDeploy && scripts.length > 1 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7" disabled={isPending} title="Run script">
                <Play className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {scripts.map((s) => (
                <DropdownMenuItem key={s.name} onClick={() => onRunScript(s)}>
                  {s.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        {canStop && isRunning && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-destructive hover:text-destructive"
            onClick={onStop}
            disabled={isStopPending}
            title="Stop"
          >
            <Square className="h-3.5 w-3.5" />
          </Button>
        )}

        {(canConfig || canFiles) && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title="Config"
            onClick={() => navigate(`/services/${name}/config`)}
          >
            <Settings className="h-3.5 w-3.5" />
          </Button>
        )}

        {isRunning && obj.data.ip && obj.data.hostname && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title="SSH"
            onClick={() => navigate(`/ssh/${obj.data.hostname}/${obj.data.ip}`)}
          >
            <Terminal className="h-3.5 w-3.5" />
          </Button>
        )}

        <Button
          variant="ghost"
          size="icon"
          className={cn(
            'h-7 w-7',
            isPinned ? 'text-amber-400 hover:text-amber-300' : 'text-muted-foreground hover:text-amber-400',
          )}
          onClick={onTogglePin}
          title={isPinned ? 'Unpin' : 'Pin'}
        >
          <Star className={cn('h-3.5 w-3.5', isPinned && 'fill-current')} />
        </Button>
      </div>
    </div>
  )
}
