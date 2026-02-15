import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Star, Play, Square, Settings, Terminal, ChevronDown, ChevronUp, ExternalLink,
  Eye, EyeOff, Copy, Pin,
} from 'lucide-react'
import { DashboardSection } from '@/components/dashboard/DashboardSection'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import { useHasPermission } from '@/lib/permissions'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { toast } from 'sonner'
import type { InventoryObject, ServiceScript } from '@/types'

export function PinnedServices() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const pinnedServices = usePreferencesStore((s) => s.preferences.pinned_services)
  const togglePin = usePreferencesStore((s) => s.togglePinService)
  const canDeploy = useHasPermission('services.deploy')
  const canStop = useHasPermission('services.stop')

  // Reuse existing queries (shared cache keys)
  const { data: serviceObjects = [] } = useQuery({
    queryKey: ['inventory', 'service'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/service')
      return (data.objects || []) as InventoryObject[]
    },
  })

  const { data: servicesData = [] } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const { data } = await api.get('/api/services')
      return data.services || []
    },
  })

  // Filter to pinned services only
  const pinned = serviceObjects.filter((obj) => {
    const name = (obj.data.name as string) || obj.name
    return pinnedServices.includes(name)
  })

  if (pinnedServices.length === 0 || pinned.length === 0) return null

  // Build scripts map
  const scriptsMap: Record<string, ServiceScript[]> = {}
  for (const svc of servicesData) {
    scriptsMap[svc.name] = svc.scripts || []
  }

  return (
    <DashboardSection
      id="pinned_services"
      title="Pinned Services"
      icon={<Pin className="h-4 w-4 text-amber-400" />}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {pinned.map((obj) => (
          <PinnedServiceCard
            key={obj.id}
            obj={obj}
            scripts={scriptsMap[(obj.data.name as string) || obj.name] || []}
            canDeploy={canDeploy}
            canStop={canStop}
            onUnpin={() => togglePin((obj.data.name as string) || obj.name)}
            onNavigate={navigate}
          />
        ))}
      </div>
    </DashboardSection>
  )
}

function PinnedServiceCard({
  obj, scripts, canDeploy, canStop, onUnpin, onNavigate,
}: {
  obj: InventoryObject
  scripts: ServiceScript[]
  canDeploy: boolean
  canStop: boolean
  onUnpin: () => void
  onNavigate: (path: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const queryClient = useQueryClient()
  const name = (obj.data.name as string) || obj.name
  const isRunning = obj.data.power_status === 'running'

  const runAction = useMutation({
    mutationFn: ({ actionName, body }: { actionName: string; body?: any }) =>
      api.post(`/api/inventory/service/${obj.id}/actions/${actionName}`, body || {}),
    onSuccess: (res) => {
      if (res.data.job_id) {
        toast.success('Action started')
        onNavigate(`/jobs/${res.data.job_id}`)
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Action failed'),
  })

  const deployScript = scripts.find((s) => s.name === 'deploy')

  return (
    <Card className={cn(
      "transition-all hover:border-border hover:shadow-md",
      isRunning && "border-l-2 border-l-emerald-500/40"
    )}>
      <CardContent className="pt-4 pb-4">
        {/* Header: name + status + actions */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className={cn(
              "h-2 w-2 rounded-full shrink-0",
              isRunning ? "bg-emerald-500 animate-status-pulse" : "bg-zinc-600"
            )} />
            <span className="font-medium text-sm truncate">{name}</span>
          </div>
          <div className="flex items-center gap-0.5">
            <Button variant="ghost" size="icon" className="h-6 w-6 text-amber-400 hover:text-amber-300"
              onClick={onUnpin} title="Unpin" aria-label={`Unpin ${name}`}>
              <Star className="h-3.5 w-3.5 fill-current" />
            </Button>
            <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground"
              onClick={() => setExpanded(!expanded)}
              aria-expanded={expanded}
              aria-label={`${expanded ? 'Collapse' : 'Expand'} ${name} outputs`}>
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </Button>
          </div>
        </div>

        {/* Quick info */}
        {isRunning && !!obj.data.ip && (
          <p className="text-xs text-muted-foreground font-mono mb-2">{String(obj.data.ip)}</p>
        )}

        {/* Action buttons */}
        <div className="flex items-center gap-1.5">
          {canDeploy && deployScript && (
            <Button size="sm" variant="outline" className="h-7 text-xs"
              onClick={() => runAction.mutate({
                actionName: 'run_script',
                body: { script: 'deploy', inputs: {} },
              })}
              disabled={runAction.isPending}>
              <Play className="mr-1 h-3 w-3" /> Deploy
            </Button>
          )}
          {canStop && isRunning && (
            <Button size="sm" variant="outline"
              className="h-7 text-xs border-destructive/40 text-destructive hover:bg-destructive/10"
              onClick={() => runAction.mutate({ actionName: 'stop' })}
              disabled={runAction.isPending}>
              <Square className="mr-1 h-3 w-3" /> Stop
            </Button>
          )}
          <div className="ml-auto flex items-center gap-0.5">
            <Button variant="ghost" size="icon" className="h-7 w-7" title="Config"
              onClick={() => onNavigate(`/services/${name}/config`)}>
              <Settings className="h-3.5 w-3.5" />
            </Button>
            {isRunning && !!obj.data.ip && !!obj.data.hostname && (
              <Button variant="ghost" size="icon" className="h-7 w-7" title="SSH"
                onClick={() => onNavigate(`/ssh/${String(obj.data.hostname)}/${String(obj.data.ip)}`)}>
                <Terminal className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>

        {/* Expanded: outputs */}
        {expanded && <PinnedServiceOutputs serviceName={name} />}
      </CardContent>
    </Card>
  )
}

function PinnedServiceOutputs({ serviceName }: { serviceName: string }) {
  const [revealedKeys, setRevealedKeys] = useState<Set<string>>(new Set())

  const { data: outputs = [] } = useQuery({
    queryKey: ['service-outputs', serviceName],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${serviceName}/outputs`)
      return (data.outputs || []) as { label: string; type: string; value: string }[]
    },
  })

  if (outputs.length === 0) return null

  return (
    <div className="mt-3 pt-3 border-t border-border/50 space-y-2">
      {outputs.map((out, i) => {
        const key = `${out.label}-${i}`
        if (out.type === 'url' && out.value) {
          return (
            <a key={key} href={out.value} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-xs text-primary hover:underline">
              <ExternalLink className="h-3 w-3 shrink-0" />
              {out.label}
            </a>
          )
        }
        if (out.type === 'credential') {
          const revealed = revealedKeys.has(key)
          return (
            <div key={key} className="flex items-center gap-1.5 text-xs">
              <span className="text-muted-foreground">{out.label}:</span>
              <span className={cn("font-mono", !revealed && "blur-sm select-none")}>{out.value}</span>
              <Button variant="ghost" size="icon" className="h-5 w-5"
                aria-label={revealed ? `Hide ${out.label}` : `Reveal ${out.label}`}
                onClick={() => setRevealedKeys((prev) => {
                  const next = new Set(prev)
                  revealed ? next.delete(key) : next.add(key)
                  return next
                })}>
                {revealed ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
              </Button>
              <Button variant="ghost" size="icon" className="h-5 w-5"
                aria-label={`Copy ${out.label}`}
                onClick={() => { navigator.clipboard.writeText(out.value); toast.success('Copied') }}>
                <Copy className="h-3 w-3" />
              </Button>
            </div>
          )
        }
        return (
          <div key={key} className="text-xs">
            <span className="text-muted-foreground">{out.label}:</span> {out.value}
          </div>
        )
      })}
    </div>
  )
}
