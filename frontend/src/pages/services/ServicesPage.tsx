import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useServiceAction } from '@/hooks/useServiceAction'
import {
  Play,
  Square,
  OctagonX,
  Shield,
  Compass,
} from 'lucide-react'
import api from '@/lib/api'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { useHasPermission } from '@/lib/permissions'
import { EmptyState } from '@/components/shared/EmptyState'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { ScriptInputField } from '@/components/shared/ScriptInputField'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
import { StageSelectModal } from '@/components/services/StageSelectModal'
import type { ServiceSummary } from '@/components/services/ServiceCrossLinks'
import { ServiceControlsBar } from '@/components/services/ServiceControlsBar'
import type { StatusFilter, GroupBy, ViewMode } from '@/components/services/ServiceControlsBar'
import { ServiceCard } from '@/components/services/ServiceCard'
import { ServiceListRow } from '@/components/services/ServiceListRow'
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
  const canSelectPlan = useHasPermission('services.plan_select')

  const {
    triggerAction,
    confirmDeploy,
    confirmStages,
    submitScriptInputs,
    dismissModals,
    dryRunModal,
    scriptModal,
    stageModal,
    scriptInputs,
    setScriptInputs,
    saveToLibrary,
    setSaveToLibrary,
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
  const pinnedServices = usePreferencesStore((s) => s.preferences.pinned_services)

  // Controls state
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [groupBy, setGroupBy] = useState<GroupBy>('none')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')

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
    setSelectedIds(new Set(filteredObjects.map(o => o.id)))
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

  // Build plan context map for services that have plan info
  const planContextMap = useMemo(() => {
    const map: Record<string, { defaultPlan?: string; minPlan?: string | null; minPlanMonthlyCost?: number | null; showPlanSelector: boolean }> = {}
    if (!canSelectPlan) return map
    for (const svc of servicesData) {
      if (svc.default_plan) {
        map[svc.name] = {
          defaultPlan: svc.default_plan,
          minPlan: svc.min_plan,
          minPlanMonthlyCost: svc.min_plan_monthly_cost ?? null,
          showPlanSelector: true,
        }
      }
    }
    return map
  }, [servicesData, canSelectPlan])

  // Filtered + sorted objects
  const filteredObjects = useMemo(() => {
    let result = serviceObjects

    // Search filter
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(obj => {
        const name = ((obj.data.name as string) || obj.name).toLowerCase()
        const hostname = ((obj.data.hostname as string) || '').toLowerCase()
        const ip = ((obj.data.ip as string) || '').toLowerCase()
        const region = ((obj.data.region as string) || '').toLowerCase()
        const tagNames = (obj.tags || []).map(t => t.name.toLowerCase())
        return name.includes(q) || hostname.includes(q) || ip.includes(q) || region.includes(q) || tagNames.some(t => t.includes(q))
      })
    }

    // Status filter
    if (statusFilter === 'running') {
      result = result.filter(obj => obj.data.power_status === 'running')
    } else if (statusFilter === 'stopped') {
      result = result.filter(obj => obj.data.power_status !== 'running')
    }

    // Pinned-first sort
    result = [...result].sort((a, b) => {
      const aName = (a.data.name as string) || a.name
      const bName = (b.data.name as string) || b.name
      const aPinned = pinnedServices.includes(aName) ? 0 : 1
      const bPinned = pinnedServices.includes(bName) ? 0 : 1
      return aPinned - bPinned
    })

    return result
  }, [serviceObjects, search, statusFilter, pinnedServices])

  // Grouped objects
  const groupedObjects = useMemo(() => {
    if (groupBy === 'none') return { '': filteredObjects }
    if (groupBy === 'tag') {
      const groups: Record<string, InventoryObject[]> = {}
      for (const obj of filteredObjects) {
        const tags = obj.tags || []
        if (tags.length === 0) {
          (groups['Untagged'] ??= []).push(obj)
        } else {
          for (const t of tags) (groups[t.name] ??= []).push(obj)
        }
      }
      return groups
    }
    // groupBy === 'region'
    const groups: Record<string, InventoryObject[]> = {}
    for (const obj of filteredObjects) (groups[(obj.data.region as string) || 'Unknown'] ??= []).push(obj)
    return groups
  }, [filteredObjects, groupBy])

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

  const hasActiveFilters = search || statusFilter !== 'all'

  return (
    <div>
      {/* Page Header */}
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
                  selectedIds.size === filteredObjects.length ? clearSelection() : selectAll()
                }>
                  {selectedIds.size === filteredObjects.length ? 'Deselect All' : 'Select All'}
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

      {/* Controls Bar */}
      <ServiceControlsBar
        search={search}
        onSearchChange={setSearch}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        groupBy={groupBy}
        onGroupByChange={setGroupBy}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
      />

      {/* Content */}
      {objectsLoading ? (
        <LoadingSkeleton viewMode={viewMode} />
      ) : filteredObjects.length === 0 ? (
        <EmptyState
          icon={<Compass className="h-12 w-12" />}
          title={hasActiveFilters ? 'No matching services' : 'No services'}
          description={
            hasActiveFilters
              ? 'Try adjusting your search or filters.'
              : 'No services are configured in the inventory.'
          }
        />
      ) : (
        Object.entries(groupedObjects).map(([group, objects]) => (
          <div key={group || '__all'} className={group ? 'mb-8' : ''}>
            {group && (
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-widest mb-4">
                {group}
              </h2>
            )}
            {viewMode === 'grid' ? (
              <div className="grid gap-5 lg:grid-cols-2">
                {objects.map((obj, index) => {
                  const name = (obj.data.name as string) || obj.name
                  return (
                    <ServiceCard
                      key={obj.id}
                      obj={obj}
                      index={index}
                      scripts={scriptsMap[name] || []}
                      summary={summariesMap[name]}
                      isSelected={selectedIds.has(obj.id)}
                      isPinned={pinnedServices.includes(name)}
                      isExpanded={expandedService === name}
                      canDeploy={canDeploy}
                      canStop={canStop}
                      canConfig={canConfig}
                      canFiles={canFiles}
                      isPending={isPending}
                      isStopPending={stopServiceMutation.isPending}
                      onToggleSelect={() => toggleSelect(obj.id)}
                      onTogglePin={() => togglePin(name)}
                      onToggleExpand={() => setExpandedService(expandedService === name ? null : name)}
                      onRunScript={(script) => triggerAction(name, obj.id, script, planContextMap[name])}
                      onStop={() => stopServiceMutation.mutate({ objId: obj.id })}
                    />
                  )
                })}
              </div>
            ) : (
              <div className="space-y-2">
                {objects.map((obj) => {
                  const name = (obj.data.name as string) || obj.name
                  return (
                    <ServiceListRow
                      key={obj.id}
                      obj={obj}
                      scripts={scriptsMap[name] || []}
                      summary={summariesMap[name]}
                      isSelected={selectedIds.has(obj.id)}
                      isPinned={pinnedServices.includes(name)}
                      canDeploy={canDeploy}
                      canStop={canStop}
                      canConfig={canConfig}
                      canFiles={canFiles}
                      isPending={isPending}
                      isStopPending={stopServiceMutation.isPending}
                      onToggleSelect={() => toggleSelect(obj.id)}
                      onTogglePin={() => togglePin(name)}
                      onRunScript={(script) => triggerAction(name, obj.id, script, planContextMap[name])}
                      onStop={() => stopServiceMutation.mutate({ objId: obj.id })}
                    />
                  )
                })}
              </div>
            )}
          </div>
        ))
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

      {/* Stage Select Modal */}
      {stageModal && (
        <StageSelectModal
          serviceName={stageModal.serviceName}
          stages={stageModal.script.stages || []}
          open={true}
          onOpenChange={(open) => { if (!open) dismissModals() }}
          onContinue={confirmStages}
          showPlanSelector={stageModal.planContext?.showPlanSelector}
          defaultPlan={stageModal.planContext?.defaultPlan}
          minPlan={stageModal.planContext?.minPlan}
          minPlanMonthlyCost={stageModal.planContext?.minPlanMonthlyCost}
        />
      )}

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
            {scriptModal?.script.inputs?.some((inp) => inp.type === 'file' || inp.type === 'multi_file') &&
              Object.values(scriptInputs).some((v) =>
                v instanceof File || (Array.isArray(v) && v.some((item: any) => item instanceof File))
              ) && (
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <Checkbox
                  checked={saveToLibrary}
                  onCheckedChange={(checked) => setSaveToLibrary(!!checked)}
                />
                <span className="text-muted-foreground">Save uploaded files to library</span>
              </label>
            )}
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

function LoadingSkeleton({ viewMode }: { viewMode: ViewMode }) {
  if (viewMode === 'list') {
    return (
      <div className="space-y-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="flex items-center gap-4 rounded-lg border border-border/50 bg-card px-4 py-3">
            <Skeleton className="h-4 w-4 rounded" />
            <Skeleton className="h-2.5 w-2.5 rounded-full" />
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-48 flex-1" />
            <Skeleton className="h-4 w-12" />
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-7 w-24" />
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="bg-card border border-border/50 rounded-xl p-6 space-y-4">
          <div className="flex items-center gap-4">
            <Skeleton className="h-4 w-4 rounded" />
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
  )
}
