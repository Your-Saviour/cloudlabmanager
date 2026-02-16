import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Search,
  LayoutGrid,
  List,
  ExternalLink,
  Compass,
  Copy,
  Terminal,
  Clock,
  Trash2,
  RefreshCw,
  User,
} from 'lucide-react'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import { EmptyState } from '@/components/shared/EmptyState'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ServicePortalCard } from '@/components/portal/ServicePortalCard'
import { toast } from 'sonner'
import { usePersonalInstances, useDestroyPersonalInstance, useExtendPersonalInstanceTTL } from '@/hooks/usePersonalInstances'
import { useHasPermission } from '@/lib/permissions'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import type { PortalService, PortalServicesResponse } from '@/types/portal'

function formatTTLRemaining(ttlHours: number | null, createdAt: string | null): string {
  if (!ttlHours || !createdAt) return 'No TTL'
  const created = new Date(createdAt)
  const expiresAt = new Date(created.getTime() + ttlHours * 60 * 60 * 1000)
  const now = new Date()
  const remainingMs = expiresAt.getTime() - now.getTime()
  if (remainingMs <= 0) return 'Expired'
  const hours = Math.floor(remainingMs / (60 * 60 * 1000))
  const minutes = Math.floor((remainingMs % (60 * 60 * 1000)) / (60 * 1000))
  if (hours > 0) return `${hours}h ${minutes}m remaining`
  return `${minutes}m remaining`
}

export default function PortalPage() {
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [searchQuery, setSearchQuery] = useState('')
  const [groupBy, setGroupBy] = useState<'none' | 'tag' | 'region'>('none')
  const canPersonal = useHasPermission('personal_instances.create')

  const { data, isLoading } = useQuery({
    queryKey: ['portal-services'],
    queryFn: async () => {
      const { data } = await api.get('/api/portal/services')
      return data as PortalServicesResponse
    },
    refetchInterval: 15000,
  })

  const filtered = useMemo(() => {
    if (!data?.services) return []
    if (!searchQuery) return data.services
    const q = searchQuery.toLowerCase()
    return data.services.filter(s =>
      s.name.includes(q) || s.display_name.toLowerCase().includes(q) ||
      s.hostname?.includes(q) || s.fqdn?.includes(q) ||
      s.ip?.includes(q) || s.tags.some(t => t.toLowerCase().includes(q))
    )
  }, [data, searchQuery])

  const grouped = useMemo(() => {
    if (groupBy === 'none') return { '': filtered }
    if (groupBy === 'tag') {
      const groups: Record<string, PortalService[]> = {}
      for (const s of filtered) {
        if (s.tags.length === 0) {
          (groups['Untagged'] ??= []).push(s)
        } else {
          for (const t of s.tags) (groups[t] ??= []).push(s)
        }
      }
      return groups
    }
    // groupBy === 'region'
    const groups: Record<string, PortalService[]> = {}
    for (const s of filtered) (groups[s.region || 'Unknown'] ??= []).push(s)
    return groups
  }, [filtered, groupBy])

  return (
    <div>
      {/* Page Header */}
      <div className="mb-8">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="font-display text-3xl font-bold tracking-tight">Service Portal</h1>
            <p className="text-muted-foreground text-sm mt-1">Access all your deployed services</p>
            <div className="w-12 h-0.5 bg-primary mt-2" />
          </div>
        </div>
      </div>

      {/* Controls Row */}
      <div className="flex items-center gap-3 mb-6">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search services..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
            aria-label="Search services"
          />
        </div>

        <Select value={groupBy} onValueChange={(v) => setGroupBy(v as 'none' | 'tag' | 'region')}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Group by..." />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">No grouping</SelectItem>
            <SelectItem value="tag">Group by tag</SelectItem>
            <SelectItem value="region">Group by region</SelectItem>
          </SelectContent>
        </Select>

        <div className="flex items-center border border-border rounded-md">
          <Button
            variant="ghost"
            size="icon"
            className={cn('h-9 w-9 rounded-r-none', viewMode === 'grid' && 'bg-muted')}
            onClick={() => setViewMode('grid')}
            aria-label="Grid view"
            aria-pressed={viewMode === 'grid'}
          >
            <LayoutGrid className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={cn('h-9 w-9 rounded-l-none', viewMode === 'list' && 'bg-muted')}
            onClick={() => setViewMode('list')}
            aria-label="List view"
            aria-pressed={viewMode === 'list'}
          >
            <List className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Personal Instances Section */}
      {canPersonal && <PersonalInstancesSection />}

      {/* Content */}
      {isLoading ? (
        <LoadingSkeleton viewMode={viewMode} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Compass className="h-12 w-12" />}
          title={searchQuery ? 'No matching services' : 'No services available'}
          description={searchQuery ? 'Try adjusting your search query.' : 'No services are currently deployed.'}
        />
      ) : (
        Object.entries(grouped).map(([group, services]) => (
          <div key={group || '__all'} className={group ? 'mb-8' : ''}>
            {group && (
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-widest mb-4">
                {group}
              </h2>
            )}
            {viewMode === 'grid' ? (
              <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
                {services.map((service, index) => (
                  <ServicePortalCard key={service.name} service={service} index={index} />
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {services.map((service) => (
                  <ServiceCardList key={service.name} service={service} />
                ))}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  )
}

function PersonalInstancesSection() {
  const { data: instances = [], isLoading } = usePersonalInstances()
  const destroyMutation = useDestroyPersonalInstance()
  const extendMutation = useExtendPersonalInstanceTTL()
  const canDestroy = useHasPermission('personal_instances.destroy')
  const [destroyTarget, setDestroyTarget] = useState<string | null>(null)

  if (isLoading) return null
  if (instances.length === 0) return null

  return (
    <div className="mb-8">
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-widest mb-4 flex items-center gap-2">
        <User className="h-4 w-4" />
        My Personal Instances
      </h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {instances.map((inst) => {
          const isRunning = inst.power_status === 'running'
          return (
            <div
              key={inst.hostname}
              className="relative overflow-hidden rounded-xl border border-border/50 bg-card p-5 hover:border-border transition-all"
            >
              {/* Status strip */}
              <div
                className={cn(
                  'absolute top-0 left-0 right-0 h-[3px]',
                  isRunning ? 'bg-emerald-500' : 'bg-zinc-600'
                )}
              />

              {/* Header */}
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="font-display text-base font-semibold">{inst.hostname}</h3>
                  <Badge variant="outline" className="text-[11px] px-2 py-0.5 mt-1">
                    {inst.service}
                  </Badge>
                </div>
                <span
                  className={cn(
                    'text-xs font-medium capitalize',
                    isRunning ? 'text-emerald-400' : 'text-zinc-500'
                  )}
                >
                  {inst.power_status || 'Unknown'}
                </span>
              </div>

              {/* Data cells */}
              <div className="flex gap-2 mb-3">
                {inst.ip_address && (
                  <div className="bg-background/50 rounded-lg px-2.5 py-2 flex-1 min-w-0">
                    <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">IP</div>
                    <div className="text-xs font-mono text-foreground truncate mt-0.5">{inst.ip_address}</div>
                  </div>
                )}
                {inst.region && (
                  <div className="bg-background/50 rounded-lg px-2.5 py-2 flex-1 min-w-0">
                    <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">Region</div>
                    <div className="text-xs text-foreground truncate mt-0.5">{inst.region}</div>
                  </div>
                )}
              </div>

              {/* TTL */}
              {inst.ttl_hours != null && (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-3">
                  <Clock className="h-3 w-3" />
                  <span>{formatTTLRemaining(inst.ttl_hours, inst.created_at)}</span>
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center gap-2 border-t border-border/50 pt-3">
                <Button
                  variant="outline"
                  size="sm"
                  className="text-xs h-7"
                  aria-label={`Extend TTL for ${inst.hostname}`}
                  onClick={() => {
                    extendMutation.mutate(inst.hostname, {
                      onSuccess: () => toast.success(`TTL extended for ${inst.hostname}`),
                      onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to extend TTL'),
                    })
                  }}
                  disabled={extendMutation.isPending}
                >
                  <RefreshCw className="mr-1 h-3 w-3" /> Extend
                </Button>
                {canDestroy && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs h-7 border-destructive/40 text-destructive hover:bg-destructive/10"
                    aria-label={`Destroy ${inst.hostname}`}
                    onClick={() => setDestroyTarget(inst.hostname)}
                  >
                    <Trash2 className="mr-1 h-3 w-3" /> Destroy
                  </Button>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <ConfirmDialog
        open={!!destroyTarget}
        onOpenChange={(open) => { if (!open) setDestroyTarget(null) }}
        title="Destroy Personal Instance"
        description={`This will permanently destroy ${destroyTarget}. Are you sure?`}
        confirmLabel="Destroy"
        variant="destructive"
        onConfirm={() => {
          if (destroyTarget) {
            destroyMutation.mutate(destroyTarget, {
              onSuccess: () => {
                toast.success(`Destroying ${destroyTarget}`)
                setDestroyTarget(null)
              },
              onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to destroy instance'),
            })
          }
        }}
      />
    </div>
  )
}

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
      <span className={cn(
        'h-2 w-2 rounded-full',
        status === 'healthy' && 'bg-emerald-500',
        status === 'unhealthy' && 'bg-red-500',
        status === 'degraded' && 'bg-amber-500',
        (status === 'unknown' || !config[status]) && 'bg-zinc-500',
      )} />
      {c.label}
    </span>
  )
}

function ServiceCardList({ service }: { service: PortalService }) {
  const isRunning = service.power_status === 'running'
  const isSuspended = service.power_status === 'suspended'
  const primaryUrl = service.outputs.find((o) => o.type === 'url')?.value

  return (
    <div className="flex items-center gap-4 rounded-lg border border-border/50 bg-card px-4 py-3 hover:border-border transition-colors max-sm:flex-wrap max-sm:gap-2">
      {/* Status Dot */}
      <span
        className={cn(
          'h-2.5 w-2.5 rounded-full shrink-0',
          isRunning ? 'bg-emerald-500 animate-status-pulse' : isSuspended ? 'bg-amber-500' : 'bg-zinc-600'
        )}
        aria-label={isRunning ? 'Running' : isSuspended ? 'Suspended' : 'Stopped'}
      />

      {/* Name */}
      <span className="font-medium text-sm min-w-[140px] max-sm:min-w-0 max-sm:flex-1">{service.display_name}</span>

      {/* FQDN or IP */}
      <span className="text-sm font-mono text-muted-foreground truncate min-w-0 flex-1 max-sm:w-full max-sm:flex-none">
        {service.fqdn ? (
          <a
            href={primaryUrl || `https://${service.fqdn}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline inline-flex items-center gap-1"
          >
            {service.fqdn} <ExternalLink className="h-3 w-3" />
          </a>
        ) : (
          service.ip || '-'
        )}
      </span>

      {/* Health */}
      <div className="min-w-[90px]">
        {service.health ? (
          <HealthBadge status={service.health.overall_status} />
        ) : (
          <HealthBadge status="unknown" />
        )}
      </div>

      {/* Region */}
      <span className="text-xs text-muted-foreground min-w-[60px]">{service.region || '-'}</span>

      {/* Action icons */}
      <div className="flex items-center gap-1 min-w-[80px] justify-end">
        {service.ip && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => {
              navigator.clipboard.writeText(`ssh root@${service.ip}`)
              toast.success('SSH command copied')
            }}
            aria-label="Copy SSH command"
          >
            <Terminal className="h-3.5 w-3.5" />
          </Button>
        )}
        {service.outputs.some((o) => o.type === 'credential') && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => {
              const cred = service.outputs.find((o) => o.type === 'credential')
              if (cred) {
                navigator.clipboard.writeText(cred.value)
                toast.success('Password copied')
              }
            }}
            aria-label="Copy first credential"
          >
            <Copy className="h-3.5 w-3.5" />
          </Button>
        )}
        {(primaryUrl || service.fqdn) && (
          <a
            href={primaryUrl || `https://${service.fqdn}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Open in browser">
              <ExternalLink className="h-3.5 w-3.5" />
            </Button>
          </a>
        )}
      </div>
    </div>
  )
}

function LoadingSkeleton({ viewMode }: { viewMode: 'grid' | 'list' }) {
  if (viewMode === 'list') {
    return (
      <div className="space-y-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="flex items-center gap-4 rounded-lg border border-border/50 bg-card px-4 py-3">
            <Skeleton className="h-2.5 w-2.5 rounded-full" />
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-4 w-48 flex-1" />
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-12" />
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <div key={i} className="bg-card border border-border/50 rounded-xl p-6 space-y-4">
          <div className="flex items-center gap-4">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-16 ml-auto" />
          </div>
          <div className="flex gap-3">
            <Skeleton className="h-14 flex-1 rounded-lg" />
            <Skeleton className="h-14 flex-1 rounded-lg" />
            <Skeleton className="h-14 flex-1 rounded-lg" />
          </div>
          <Skeleton className="h-10 w-full rounded-lg" />
          <Skeleton className="h-8 w-full rounded-lg" />
          <Skeleton className="h-4 w-24" />
        </div>
      ))}
    </div>
  )
}
