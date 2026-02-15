import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useServiceAction } from '@/hooks/useServiceAction'
import {
  Play,
  Square,
  Settings,
  FolderOpen,
  OctagonX,
  Terminal,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Eye,
  EyeOff,
  Copy,
  Plus,
  X,
  Star,
  Shield,
} from 'lucide-react'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { useHasPermission } from '@/lib/permissions'
import { EmptyState } from '@/components/shared/EmptyState'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { ScriptInputField } from '@/components/shared/ScriptInputField'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { toast } from 'sonner'
import { DryRunPreview } from '@/components/services/DryRunPreview'
import { ServiceCrossLinks } from '@/components/services/ServiceCrossLinks'
import type { ServiceSummary } from '@/components/services/ServiceCrossLinks'
import { BulkActionBar } from '@/components/shared/BulkActionBar'
import type { InventoryObject, ServiceScript, Role, ServicePermission } from '@/types'

const ALL_PERMISSIONS: { value: ServicePermission; label: string; color: string }[] = [
  { value: 'view', label: 'View', color: 'bg-blue-500/15 text-blue-400 border-blue-500/30' },
  { value: 'deploy', label: 'Deploy', color: 'bg-green-500/15 text-green-400 border-green-500/30' },
  { value: 'stop', label: 'Stop', color: 'bg-red-500/15 text-red-400 border-red-500/30' },
  { value: 'config', label: 'Config', color: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
]

export default function ServicesPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const canDeploy = useHasPermission('services.deploy')
  const canStop = useHasPermission('services.stop')
  const canStopAll = useHasPermission('system.stop_all')
  const canConfig = useHasPermission('services.config.view')
  const canFiles = useHasPermission('services.files.view')
  const canManageACL = useHasPermission('inventory.acl.manage')

  const {
    triggerAction,
    confirmDeploy,
    submitScriptInputs,
    dismissModals,
    dryRunModal,
    scriptModal,
    scriptInputs,
    setScriptInputs,
    isPending,
  } = useServiceAction()

  const [stopAllOpen, setStopAllOpen] = useState(false)
  const [expandedService, setExpandedService] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [bulkStopOpen, setBulkStopOpen] = useState(false)
  const [bulkDeployOpen, setBulkDeployOpen] = useState(false)
  const [bulkAclOpen, setBulkAclOpen] = useState(false)
  const [bulkAclForm, setBulkAclForm] = useState<{ role_id: string; permissions: ServicePermission[] }>({ role_id: '', permissions: [] })
  const togglePin = usePreferencesStore((s) => s.togglePinService)
  const isServicePinned = usePreferencesStore((s) => s.isServicePinned)

  // Get service inventory objects
  const { data: serviceObjects = [], isLoading: objectsLoading } = useQuery({
    queryKey: ['inventory', 'service'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/service')
      return (data.objects || []) as InventoryObject[]
    },
  })

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAll = () => {
    setSelectedIds(new Set(serviceObjects.map(o => o.id)))
  }

  const clearSelection = () => setSelectedIds(new Set())

  // Get service scripts from the services API
  const { data: servicesData = [] } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const { data } = await api.get('/api/services')
      return data.services || []
    },
  })

  // Get cross-link summaries for all services
  const { data: summariesMap = {} } = useQuery({
    queryKey: ['service-summaries'],
    queryFn: async () => {
      const { data } = await api.get('/api/services/summaries')
      return (data.summaries || {}) as Record<string, ServiceSummary>
    },
    refetchInterval: 30000,
  })

  // Get roles for bulk ACL assignment
  const { data: roles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: async () => {
      const { data } = await api.get('/api/roles')
      return (data.roles || []) as Role[]
    },
    enabled: canManageACL,
  })

  // Build scripts map: service name -> scripts[]
  const scriptsMap: Record<string, ServiceScript[]> = {}
  for (const svc of servicesData) {
    scriptsMap[svc.name] = svc.scripts || []
  }

  // Compute status counts
  const runningCount = serviceObjects.filter((o) => o.data.power_status === 'running').length
  const stoppedCount = serviceObjects.filter((o) => o.data.power_status !== 'running').length

  const stopServiceMutation = useMutation({
    mutationFn: ({ objId }: { objId: number }) =>
      api.post(`/api/inventory/service/${objId}/actions/stop`, {}),
    onSuccess: (res) => {
      if (res.data.job_id) {
        toast.success('Action started')
        navigate(`/jobs/${res.data.job_id}`)
      } else {
        toast.success('Action completed')
        queryClient.invalidateQueries({ queryKey: ['active-deployments'] })
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Action failed'),
  })

  const stopAllMutation = useMutation({
    mutationFn: () => api.post('/api/services/actions/stop-all'),
    onSuccess: (res) => {
      setStopAllOpen(false)
      if (res.data.job_id) navigate(`/jobs/${res.data.job_id}`)
    },
    onError: () => toast.error('Stop all failed'),
  })

  const bulkStopMutation = useMutation({
    mutationFn: (serviceNames: string[]) =>
      api.post('/api/services/actions/bulk-stop', { service_names: serviceNames }),
    onSuccess: (res) => {
      clearSelection()
      setBulkStopOpen(false)
      if (res.data.job_id) navigate(`/jobs/${res.data.job_id}`)
      if (res.data.skipped?.length > 0) {
        toast.warning(`${res.data.skipped.length} services skipped`)
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Bulk stop failed'),
  })

  const bulkDeployMutation = useMutation({
    mutationFn: (serviceNames: string[]) =>
      api.post('/api/services/actions/bulk-deploy', { service_names: serviceNames }),
    onSuccess: (res) => {
      clearSelection()
      setBulkDeployOpen(false)
      if (res.data.job_id) navigate(`/jobs/${res.data.job_id}`)
      if (res.data.skipped?.length > 0) {
        toast.warning(`${res.data.skipped.length} services skipped`)
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Bulk deploy failed'),
  })

  const bulkAclMutation = useMutation({
    mutationFn: (body: { service_names: string[]; role_id: number; permissions: string[] }) =>
      api.post('/api/services/actions/bulk-acl', body),
    onSuccess: (res) => {
      clearSelection()
      setBulkAclOpen(false)
      setBulkAclForm({ role_id: '', permissions: [] })
      const succeeded = res.data.succeeded?.length ?? 0
      toast.success(`Access granted to ${succeeded} service${succeeded !== 1 ? 's' : ''}`)
      if (res.data.skipped?.length > 0) {
        toast.warning(`${res.data.skipped.length} services skipped`)
      }
      queryClient.invalidateQueries({ queryKey: ['inventory', 'service'] })
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Bulk ACL failed'),
  })

  const toggleBulkPermission = (perm: ServicePermission) => {
    setBulkAclForm(prev => ({
      ...prev,
      permissions: prev.permissions.includes(perm)
        ? prev.permissions.filter(p => p !== perm)
        : [...prev.permissions, perm],
    }))
  }

  return (
    <div>
      {/* Custom Page Header */}
      <div className="mb-8">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="font-display text-3xl font-bold tracking-tight">Services</h1>
            <p className="text-muted-foreground text-sm mt-1">Deploy and manage infrastructure services</p>
            <div className="w-12 h-0.5 bg-primary mt-2" />
            {!objectsLoading && serviceObjects.length > 0 && (
              <div className="flex items-center gap-3 mt-3 text-sm text-muted-foreground">
                {runningCount > 0 && (
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-emerald-500 animate-status-pulse" />
                    <span>{runningCount} active</span>
                  </span>
                )}
                {runningCount > 0 && stoppedCount > 0 && <span className="text-border">·</span>}
                {stoppedCount > 0 && (
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-zinc-600" />
                    <span>{stoppedCount} stopped</span>
                  </span>
                )}
                <span className="text-border">·</span>
                <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() =>
                  selectedIds.size === serviceObjects.length ? clearSelection() : selectAll()
                }>
                  {selectedIds.size === serviceObjects.length ? 'Deselect All' : 'Select All'}
                </Button>
              </div>
            )}
          </div>
          {canStopAll && (
            <Button variant="destructive" size="sm" onClick={() => setStopAllOpen(true)}>
              <OctagonX className="mr-2 h-3 w-3" /> Stop All
            </Button>
          )}
        </div>
      </div>

      {objectsLoading ? (
        <div className="grid gap-5 lg:grid-cols-2">
          {[1, 2, 3].map((i) => (
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
              <Skeleton className="h-9 w-32" />
            </div>
          ))}
        </div>
      ) : serviceObjects.length === 0 ? (
        <EmptyState title="No services" description="No services are configured in the inventory." />
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          {serviceObjects.map((obj, index) => {
            const name = obj.data.name as string || obj.name
            const powerStatus = obj.data.power_status as string | undefined
            const isRunning = powerStatus === 'running'
            const isSuspended = powerStatus === 'suspended'
            const scripts = scriptsMap[name] || []
            const tags = obj.tags || []
            const isExpanded = expandedService === name

            return (
              <div
                key={obj.id}
                className={`
                  relative overflow-hidden rounded-xl border border-border/50
                  bg-card p-6 hover:border-border hover:shadow-lg hover:shadow-primary/5
                  transition-all duration-300 animate-card-in
                  ${isRunning ? 'border-l-2 border-l-emerald-500/40' : ''}
                `}
                style={{ animationDelay: `${index * 60}ms` }}
              >
                {/* Zone A: Status Strip */}
                <div
                  className={`absolute top-0 left-0 right-0 h-[3px] ${
                    isRunning
                      ? 'bg-emerald-500 glow-emerald'
                      : isSuspended
                        ? 'bg-amber-500'
                        : 'bg-zinc-600'
                  }`}
                />

                {/* Zone A: Identity */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-start gap-3">
                    {/* Selection checkbox */}
                    <Checkbox
                      checked={selectedIds.has(obj.id)}
                      onCheckedChange={() => toggleSelect(obj.id)}
                      className="mt-1"
                      aria-label={`Select ${name}`}
                    />
                    <div>
                    <h3 className="font-display text-lg font-semibold">{name}</h3>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="flex items-center gap-1.5">
                        <span
                          className={`h-2 w-2 rounded-full ${
                            isRunning
                              ? 'bg-emerald-500 animate-status-pulse'
                              : isSuspended
                                ? 'bg-amber-500'
                                : 'bg-zinc-600'
                          }`}
                        />
                        <span
                          className={`text-xs font-medium ${
                            isRunning
                              ? 'text-emerald-400'
                              : isSuspended
                                ? 'text-amber-400'
                                : 'text-zinc-500'
                          }`}
                        >
                          {powerStatus ? powerStatus.charAt(0).toUpperCase() + powerStatus.slice(1) : 'Unknown'}
                        </span>
                      </span>
                    </div>
                    {tags.length > 0 && (
                      <div className="flex gap-1.5 mt-2 flex-wrap">
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
                    {/* Cross-link chips */}
                    <ServiceCrossLinks
                      serviceName={name}
                      summary={summariesMap[name]}
                    />
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    {/* Pin toggle */}
                    <Button
                      variant="ghost"
                      size="icon"
                      className={cn(
                        "h-7 w-7",
                        isServicePinned(name)
                          ? "text-amber-400 hover:text-amber-300"
                          : "text-muted-foreground hover:text-amber-400"
                      )}
                      onClick={(e) => {
                        e.stopPropagation()
                        togglePin(name)
                      }}
                      title={isServicePinned(name) ? "Unpin from dashboard" : "Pin to dashboard"}
                      aria-label={isServicePinned(name) ? `Unpin ${name} from dashboard` : `Pin ${name} to dashboard`}
                    >
                      <Star
                        className={cn("h-4 w-4", isServicePinned(name) && "fill-current")}
                      />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground"
                      onClick={() => setExpandedService(isExpanded ? null : name)}
                    >
                      {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    </Button>
                  </div>
                </div>

                {/* Zone B: Data Cells */}
                <div className="flex gap-3 mb-4">
                  {obj.data.hostname && (
                    <div className="bg-background/50 rounded-lg px-3 py-2.5 flex-1 min-w-0">
                      <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">Hostname</div>
                      <div className="text-sm text-foreground truncate mt-0.5">{String(obj.data.hostname)}</div>
                    </div>
                  )}
                  {obj.data.ip && (
                    <div className="bg-background/50 rounded-lg px-3 py-2.5 flex-1 min-w-0">
                      <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">IP Address</div>
                      <div className="text-sm font-mono text-foreground truncate mt-0.5">{String(obj.data.ip)}</div>
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
                {isExpanded && <ServiceOutputsPanel serviceName={name} />}

                {/* Zone C: Actions Bar */}
                <div className="flex items-center justify-between border-t border-border/50 pt-4 mt-4">
                  <div className="flex items-center gap-2">
                    {/* Script selector + run */}
                    {canDeploy && scripts.length > 0 && (
                      <ScriptRunner
                        scripts={scripts}
                        onRun={(script) => triggerAction(name, obj.id, script)}
                        disabled={isPending}
                      />
                    )}

                    {/* Stop */}
                    {canStop && isRunning && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="border-destructive/40 text-destructive hover:bg-destructive/10"
                        onClick={() => stopServiceMutation.mutate({ objId: obj.id })}
                        disabled={stopServiceMutation.isPending}
                      >
                        <Square className="mr-1 h-3 w-3" /> Stop
                      </Button>
                    )}
                  </div>

                  <div className="flex items-center gap-1">
                    {/* Config */}
                    {canConfig && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9"
                        title="Config"
                        onClick={() => navigate(`/services/${name}/config`)}
                      >
                        <Settings className="h-4 w-4" />
                      </Button>
                    )}

                    {/* Files */}
                    {canFiles && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9"
                        title="Files"
                        onClick={() => navigate(`/services/${name}/files`)}
                      >
                        <FolderOpen className="h-4 w-4" />
                      </Button>
                    )}

                    {/* SSH - only show when running */}
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
          })}
        </div>
      )}

      {/* Stop All Confirm */}
      <ConfirmDialog
        open={stopAllOpen}
        onOpenChange={setStopAllOpen}
        title="Stop All Instances"
        description="This will stop all running instances. Are you sure?"
        confirmLabel="Stop All"
        variant="destructive"
        onConfirm={() => stopAllMutation.mutate()}
      />

      {/* Bulk Stop Confirm */}
      <ConfirmDialog
        open={bulkStopOpen}
        onOpenChange={setBulkStopOpen}
        title={`Stop ${selectedIds.size} Services`}
        description={`This will stop ${selectedIds.size} selected services. Are you sure?`}
        confirmLabel="Stop Selected"
        variant="destructive"
        onConfirm={() => {
          const names = serviceObjects
            .filter(o => selectedIds.has(o.id))
            .map(o => (o.data.name as string) || o.name)
          bulkStopMutation.mutate(names)
        }}
      />

      {/* Bulk Deploy Confirm */}
      <ConfirmDialog
        open={bulkDeployOpen}
        onOpenChange={setBulkDeployOpen}
        title={`Deploy ${selectedIds.size} Services`}
        description={`This will deploy ${selectedIds.size} selected services. Are you sure?`}
        confirmLabel="Deploy Selected"
        onConfirm={() => {
          const names = serviceObjects
            .filter(o => selectedIds.has(o.id))
            .map(o => (o.data.name as string) || o.name)
          bulkDeployMutation.mutate(names)
        }}
      />

      {/* Bulk ACL Assignment */}
      <Dialog open={bulkAclOpen} onOpenChange={(open) => {
        setBulkAclOpen(open)
        if (!open) setBulkAclForm({ role_id: '', permissions: [] })
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Grant Service Access</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Assign permissions to a role for {selectedIds.size} selected service{selectedIds.size !== 1 ? 's' : ''}.
            </p>
            <div className="space-y-2">
              <Label>Role</Label>
              <Select value={bulkAclForm.role_id} onValueChange={(v) => setBulkAclForm(prev => ({ ...prev, role_id: v }))}>
                <SelectTrigger>
                  <SelectValue placeholder="Select role..." />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)}>{r.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Permissions</Label>
              <div className="flex flex-wrap gap-3">
                {ALL_PERMISSIONS.map((perm) => (
                  <label key={perm.value} className="flex items-center gap-2 cursor-pointer">
                    <Checkbox
                      checked={bulkAclForm.permissions.includes(perm.value)}
                      onCheckedChange={() => toggleBulkPermission(perm.value)}
                    />
                    <Badge variant="outline" className={perm.color}>
                      {perm.label}
                    </Badge>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkAclOpen(false)}>Cancel</Button>
            <Button
              disabled={!bulkAclForm.role_id || bulkAclForm.permissions.length === 0 || bulkAclMutation.isPending}
              onClick={() => {
                const names = serviceObjects
                  .filter(o => selectedIds.has(o.id))
                  .map(o => (o.data.name as string) || o.name)
                bulkAclMutation.mutate({
                  service_names: names,
                  role_id: Number(bulkAclForm.role_id),
                  permissions: bulkAclForm.permissions,
                })
              }}
            >
              {bulkAclMutation.isPending ? 'Applying...' : `Apply to ${selectedIds.size} service${selectedIds.size !== 1 ? 's' : ''}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk Action Bar */}
      <BulkActionBar
        selectedCount={selectedIds.size}
        onClear={clearSelection}
        itemLabel="services"
        actions={[
          ...(canDeploy ? [{
            label: 'Deploy',
            icon: <Play className="h-3.5 w-3.5" />,
            onClick: () => setBulkDeployOpen(true),
          }] : []),
          ...(canStop ? [{
            label: 'Stop',
            icon: <Square className="h-3.5 w-3.5" />,
            variant: 'destructive' as const,
            onClick: () => setBulkStopOpen(true),
          }] : []),
          ...(canManageACL ? [{
            label: 'Manage Access',
            icon: <Shield className="h-3.5 w-3.5" />,
            onClick: () => setBulkAclOpen(true),
          }] : []),
        ]}
      />

      {/* Dry Run Preview Modal */}
      {dryRunModal && (
        <DryRunPreview
          serviceName={dryRunModal.serviceName}
          open={true}
          onOpenChange={(open) => { if (!open) dismissModals() }}
          onConfirm={confirmDeploy}
        />
      )}

      {/* Script Input Modal */}
      <Dialog open={!!scriptModal} onOpenChange={() => dismissModals()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {scriptModal?.script.label || scriptModal?.script.name}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {scriptModal?.script.inputs?.map((inp) => (
              <ScriptInputField
                key={inp.name}
                input={inp}
                value={scriptInputs[inp.name] ?? (inp.type === 'list' ? [''] : inp.type === 'ssh_key_select' ? [] : '')}
                onChange={(val) => setScriptInputs({ ...scriptInputs, [inp.name]: val })}
                serviceName={scriptModal.serviceName}
              />
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => dismissModals()}>Cancel</Button>
            <Button onClick={submitScriptInputs} disabled={isPending}>Run</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// Service Outputs Panel
function ServiceOutputsPanel({ serviceName }: { serviceName: string }) {
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

function ScriptRunner({
  scripts,
  onRun,
  disabled,
}: {
  scripts: ServiceScript[]
  onRun: (script: ServiceScript) => void
  disabled: boolean
}) {
  const [selected, setSelected] = useState(scripts[0]?.name || '')

  if (scripts.length === 1) {
    return (
      <Button
        onClick={() => onRun(scripts[0])}
        disabled={disabled}
      >
        <Play className="mr-1.5 h-3.5 w-3.5" /> {scripts[0].label}
      </Button>
    )
  }

  return (
    <div className="flex">
      <Select value={selected} onValueChange={setSelected}>
        <SelectTrigger className="h-9 text-xs w-36 rounded-r-none border-r-0">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {scripts.map((s) => (
            <SelectItem key={s.name} value={s.name}>{s.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        className="rounded-l-none"
        onClick={() => {
          const script = scripts.find((s) => s.name === selected)
          if (script) onRun(script)
        }}
        disabled={disabled}
      >
        <Play className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

