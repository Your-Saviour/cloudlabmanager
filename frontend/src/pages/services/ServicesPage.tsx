import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
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
} from 'lucide-react'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { EmptyState } from '@/components/shared/EmptyState'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
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
import type { InventoryObject, ServiceScript, ScriptInput } from '@/types'

export default function ServicesPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const canDeploy = useHasPermission('services.deploy')
  const canStop = useHasPermission('services.stop')
  const canStopAll = useHasPermission('system.stop_all')
  const canConfig = useHasPermission('services.config.view')
  const canFiles = useHasPermission('services.files.view')

  const [stopAllOpen, setStopAllOpen] = useState(false)
  const [expandedService, setExpandedService] = useState<string | null>(null)
  const [scriptModal, setScriptModal] = useState<{
    serviceName: string
    objId: number
    script: ServiceScript
  } | null>(null)
  const [scriptInputs, setScriptInputs] = useState<Record<string, any>>({})
  const [dryRunModal, setDryRunModal] = useState<{
    serviceName: string
    objId: number
    script: ServiceScript
  } | null>(null)

  // Get service inventory objects
  const { data: serviceObjects = [], isLoading: objectsLoading } = useQuery({
    queryKey: ['inventory', 'service'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/service')
      return (data.objects || []) as InventoryObject[]
    },
  })

  // Get service scripts from the services API
  const { data: servicesData = [] } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const { data } = await api.get('/api/services')
      return data.services || []
    },
  })

  // Build scripts map: service name -> scripts[]
  const scriptsMap: Record<string, ServiceScript[]> = {}
  for (const svc of servicesData) {
    scriptsMap[svc.name] = svc.scripts || []
  }

  // Compute status counts
  const runningCount = serviceObjects.filter((o) => o.data.power_status === 'running').length
  const stoppedCount = serviceObjects.filter((o) => o.data.power_status !== 'running').length

  const runActionMutation = useMutation({
    mutationFn: ({ objId, actionName, body }: { objId: number; actionName: string; body?: any }) =>
      api.post(`/api/inventory/service/${objId}/actions/${actionName}`, body || {}),
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

  const handleRunScript = (serviceName: string, objId: number, script: ServiceScript) => {
    if (script.name === 'deploy') {
      // Show dry-run preview first
      setDryRunModal({ serviceName, objId, script })
    } else if (script.inputs && script.inputs.length > 0) {
      // Show input modal
      const defaults: Record<string, any> = {}
      script.inputs.forEach((inp) => {
        if (inp.type === 'list') {
          defaults[inp.name] = inp.default ? [inp.default] : ['']
        } else if (inp.type === 'ssh_key_select') {
          defaults[inp.name] = []
        } else {
          if (inp.default) defaults[inp.name] = inp.default
        }
      })
      setScriptInputs(defaults)
      setScriptModal({ serviceName, objId, script })
    } else {
      // Run directly
      runActionMutation.mutate({
        objId,
        actionName: 'run_script',
        body: { script: script.name, inputs: {} },
      })
    }
  }

  const submitScriptModal = () => {
    if (!scriptModal) return
    // Process list inputs: filter empty strings
    const processed: Record<string, any> = {}
    for (const [key, val] of Object.entries(scriptInputs)) {
      if (Array.isArray(val)) {
        processed[key] = val.filter((v: string) => v.trim() !== '')
      } else {
        processed[key] = val
      }
    }
    runActionMutation.mutate({
      objId: scriptModal.objId,
      actionName: 'run_script',
      body: { script: scriptModal.script.name, inputs: processed },
    })
    setScriptModal(null)
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
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-muted-foreground"
                    onClick={() => setExpandedService(isExpanded ? null : name)}
                  >
                    {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                  </Button>
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
                        onRun={(script) => handleRunScript(name, obj.id, script)}
                        disabled={runActionMutation.isPending}
                      />
                    )}

                    {/* Stop */}
                    {canStop && isRunning && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="border-destructive/40 text-destructive hover:bg-destructive/10"
                        onClick={() => runActionMutation.mutate({ objId: obj.id, actionName: 'stop' })}
                        disabled={runActionMutation.isPending}
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

      {/* Dry Run Preview Modal */}
      {dryRunModal && (
        <DryRunPreview
          serviceName={dryRunModal.serviceName}
          open={true}
          onOpenChange={(open) => { if (!open) setDryRunModal(null) }}
          onConfirm={() => {
            runActionMutation.mutate({
              objId: dryRunModal.objId,
              actionName: 'run_script',
              body: { script: dryRunModal.script.name, inputs: {} },
            })
            setDryRunModal(null)
          }}
        />
      )}

      {/* Script Input Modal */}
      <Dialog open={!!scriptModal} onOpenChange={() => setScriptModal(null)}>
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
            <Button variant="outline" onClick={() => setScriptModal(null)}>Cancel</Button>
            <Button onClick={submitScriptModal}>Run</Button>
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

function ScriptInputField({
  input,
  value,
  onChange,
  serviceName,
}: {
  input: ScriptInput
  value: any
  onChange: (val: any) => void
  serviceName: string
}) {
  // For deployment_id / deployment_select type, load active deployments
  const isDeploymentType = input.type === 'deployment_id' || input.type === 'deployment_select'
  const { data: deployments = [] } = useQuery({
    queryKey: ['active-deployments'],
    queryFn: async () => {
      const { data } = await api.get('/api/services/active-deployments')
      return (data.deployments || []) as { name: string }[]
    },
    enabled: isDeploymentType,
  })

  // For ssh_key_select type, load SSH keys
  const { data: sshKeys = [] } = useQuery({
    queryKey: ['all-ssh-keys'],
    queryFn: async () => {
      const { data } = await api.get('/api/auth/ssh-keys')
      return (data.keys || []) as { user_id: number; username: string; display_name: string; ssh_public_key: string; is_self: boolean }[]
    },
    enabled: input.type === 'ssh_key_select',
  })

  // ssh_key_select: multi-checkbox
  if (input.type === 'ssh_key_select') {
    const selectedKeys = (value as string[]) || []
    return (
      <div className="space-y-2">
        <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
        <div className="space-y-2 max-h-48 overflow-auto border rounded-md p-2">
          {sshKeys.length === 0 ? (
            <p className="text-xs text-muted-foreground">No SSH keys available</p>
          ) : (
            sshKeys.map((key) => {
              const keyId = String(key.user_id)
              const isChecked = selectedKeys.includes(keyId)
              return (
                <label key={key.user_id} className="flex items-center gap-2 text-sm cursor-pointer">
                  <Checkbox
                    checked={isChecked}
                    onCheckedChange={(checked) => {
                      if (checked) {
                        onChange([...selectedKeys, keyId])
                      } else {
                        onChange(selectedKeys.filter((k: string) => k !== keyId))
                      }
                    }}
                  />
                  <span>{key.display_name || key.username}</span>
                  <span className="text-muted-foreground text-xs">@{key.username}</span>
                  {key.is_self && (
                    <Badge variant="outline" className="text-[10px] px-1 py-0">you</Badge>
                  )}
                </label>
              )
            })
          )}
        </div>
      </div>
    )
  }

  // list: dynamic add/remove rows
  if (input.type === 'list') {
    const rows = (value as string[]) || ['']
    return (
      <div className="space-y-2">
        <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
        <div className="space-y-2">
          {rows.map((row: string, idx: number) => (
            <div key={idx} className="flex gap-2">
              <Input
                value={row}
                onChange={(e) => {
                  const updated = [...rows]
                  updated[idx] = e.target.value
                  onChange(updated)
                }}
                placeholder={input.default || ''}
              />
              {rows.length > 1 && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0"
                  onClick={() => onChange(rows.filter((_: string, i: number) => i !== idx))}
                >
                  <X className="h-3 w-3" />
                </Button>
              )}
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() => onChange([...rows, ''])}
          >
            <Plus className="mr-1 h-3 w-3" /> Add
          </Button>
        </div>
      </div>
    )
  }

  // select with options
  if (input.type === 'select' && input.options) {
    return (
      <div className="space-y-2">
        <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
        <Select value={value as string} onValueChange={onChange}>
          <SelectTrigger><SelectValue placeholder="Select..." /></SelectTrigger>
          <SelectContent>
            {input.options.map((opt) => (
              <SelectItem key={opt} value={opt}>{opt}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  // deployment_id / deployment_select
  if (isDeploymentType) {
    return (
      <div className="space-y-2">
        <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
        <Select value={value as string} onValueChange={onChange}>
          <SelectTrigger><SelectValue placeholder="Select deployment..." /></SelectTrigger>
          <SelectContent>
            {deployments.map((d: any) => (
              <SelectItem key={d.name} value={d.name}>{d.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  // Default: text input
  return (
    <div className="space-y-2">
      <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
      <Input
        value={value as string}
        onChange={(e) => onChange(e.target.value)}
        placeholder={input.default || ''}
        required={input.required}
      />
    </div>
  )
}
