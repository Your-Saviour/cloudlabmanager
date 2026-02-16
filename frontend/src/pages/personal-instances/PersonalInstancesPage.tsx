import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash, ExternalLink, Copy, Monitor, TimerReset } from 'lucide-react'
import { toast } from 'sonner'

import { useHasPermission } from '@/lib/permissions'
import {
  usePersonalServices,
  usePersonalInstances,
  usePersonalInstanceConfig,
  useCreatePersonalInstance,
  useDestroyPersonalInstance,
  useExtendPersonalInstanceTTL,
  type PersonalInstance,
} from '@/hooks/usePersonalInstances'

import { PageHeader } from '@/components/shared/PageHeader'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const DOMAIN = 'ye-et.com'

const REGIONS: { value: string; label: string }[] = [
  { value: 'mel', label: 'Melbourne (mel)' },
  { value: 'syd', label: 'Sydney (syd)' },
]

function formatTTL(ttlHours: number | null, createdAt: string | null): { text: string; color: string } | null {
  if (!ttlHours || ttlHours === 0 || !createdAt) return null
  const created = new Date(createdAt)
  const expiresAt = new Date(created.getTime() + ttlHours * 60 * 60 * 1000)
  const now = new Date()
  const remainingMs = expiresAt.getTime() - now.getTime()
  if (remainingMs <= 0) return { text: 'Expired', color: 'text-red-500' }

  const hours = Math.floor(remainingMs / (60 * 60 * 1000))
  const minutes = Math.floor((remainingMs % (60 * 60 * 1000)) / (60 * 1000))
  const text = hours > 0 ? `${hours}h ${minutes}m remaining` : `${minutes}m remaining`

  let color = ''
  if (remainingMs < 15 * 60 * 1000) color = 'text-red-500'
  else if (remainingMs < 60 * 60 * 1000) color = 'text-amber-500'

  return { text, color }
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).then(
    () => toast.success('Copied to clipboard'),
    () => toast.error('Failed to copy to clipboard'),
  )
}

export default function PersonalInstancesPage() {
  const navigate = useNavigate()
  const canCreate = useHasPermission('personal_instances.create')
  const canDestroy = useHasPermission('personal_instances.destroy')

  const { data: services = [] } = usePersonalServices()
  const [activeTab, setActiveTab] = useState('all')
  const serviceFilter = activeTab === 'all' ? undefined : activeTab
  const { data: hosts = [], isLoading } = usePersonalInstances(serviceFilter)

  const createMutation = useCreatePersonalInstance()
  const destroyMutation = useDestroyPersonalInstance()
  const extendMutation = useExtendPersonalInstanceTTL()

  const [createOpen, setCreateOpen] = useState(false)
  const [createService, setCreateService] = useState('')
  const [createRegion, setCreateRegion] = useState('')
  const [createInputs, setCreateInputs] = useState<Record<string, string>>({})
  const [destroyHost, setDestroyHost] = useState<PersonalInstance | null>(null)

  // Load config for the selected service in the create dialog
  const { data: selectedConfig } = usePersonalInstanceConfig(createService)

  // Per-service limit display
  const limitText = useMemo(() => {
    if (services.length === 0) return null
    // When filtered to a single service, show that service's limit
    if (serviceFilter) {
      const svc = services.find((s) => s.service === serviceFilter)
      const max = svc?.config.max_per_user ?? 0
      return max > 0 ? `${hosts.length}/${max} used` : `${hosts.length} active`
    }
    // When showing all, show per-service breakdown
    return services
      .map((svc) => {
        const count = hosts.filter((h) => h.service === svc.service).length
        const max = svc.config.max_per_user
        return max > 0 ? `${svc.service}: ${count}/${max}` : `${svc.service}: ${count}`
      })
      .join(' | ')
  }, [services, hosts, serviceFilter])

  const handleCreate = () => {
    if (!createService) {
      toast.error('Please select a service')
      return
    }
    const region = createRegion || selectedConfig?.default_region || 'mel'
    const inputs = Object.keys(createInputs).length > 0 ? createInputs : undefined
    createMutation.mutate(
      { service: createService, region, inputs },
      {
        onSuccess: (data) => {
          toast.success(`Creating instance: ${data.hostname}`)
          setCreateOpen(false)
          resetCreateDialog()
          if (data.job_id) navigate(`/jobs/${data.job_id}`)
        },
        onError: (err: any) => {
          toast.error(err.response?.data?.detail || 'Failed to create instance')
        },
      },
    )
  }

  const resetCreateDialog = () => {
    setCreateService('')
    setCreateRegion('')
    setCreateInputs({})
  }

  const handleDestroy = () => {
    if (!destroyHost) return
    destroyMutation.mutate(destroyHost.hostname, {
      onSuccess: (data) => {
        toast.success(`Destroying ${destroyHost.hostname}`)
        setDestroyHost(null)
        if (data.job_id) navigate(`/jobs/${data.job_id}`)
      },
      onError: (err: any) => {
        toast.error(err.response?.data?.detail || 'Failed to destroy instance')
      },
    })
  }

  // Check if create button should be disabled (at limit for selected service or all services)
  const createDisabled = useMemo(() => {
    if (services.length === 0) return true
    // If only one service, check its limit
    if (services.length === 1) {
      const max = services[0].config.max_per_user
      return max > 0 && hosts.length >= max
    }
    // If multiple services, don't disable — let the dialog handle per-service limits
    return false
  }, [services, hosts])

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="My Instances" description="Personal cloud instances">
        {canCreate && (
          <Button
            size="sm"
            onClick={() => setCreateOpen(true)}
            disabled={createDisabled}
          >
            <Plus className="mr-2 h-4 w-4" />
            Create
          </Button>
        )}
      </PageHeader>

      {/* Service filter tabs */}
      {services.length > 1 && (
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            {services.map((svc) => (
              <TabsTrigger key={svc.service} value={svc.service}>
                {svc.service}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      )}

      {/* Limit indicator */}
      {limitText && (
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{limitText}</Badge>
        </div>
      )}

      {/* Instance cards */}
      {hosts.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Monitor className="mx-auto h-10 w-10 text-muted-foreground mb-3" />
            <p className="text-muted-foreground">No personal instances running.</p>
            {canCreate && (
              <p className="text-sm text-muted-foreground mt-1">
                Click "Create" to provision a personal instance.
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {hosts.map((host) => {
            const url = `https://${host.hostname}.${DOMAIN}`
            const ttl = formatTTL(host.ttl_hours, host.created_at)
            return (
              <Card key={host.hostname}>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <CardTitle className="text-base font-mono">{host.hostname}</CardTitle>
                      <Badge variant="outline">{host.service}</Badge>
                    </div>
                    <StatusBadge status={host.power_status} />
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                    <div>
                      <span className="text-muted-foreground">Region</span>
                      <p>{host.region || '-'}</p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Plan</span>
                      <p>{host.plan || '-'}</p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">User</span>
                      <p>{host.owner}</p>
                    </div>
                    {ttl && (
                      <div>
                        <span className="text-muted-foreground">TTL</span>
                        <p className={ttl.color}>{ttl.text}</p>
                      </div>
                    )}
                  </div>

                  {/* URL row */}
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-muted-foreground shrink-0">URL</span>
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary hover:underline truncate"
                    >
                      {url}
                    </a>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 shrink-0"
                          aria-label="Copy URL to clipboard"
                          onClick={() => copyToClipboard(url)}
                        >
                          <Copy className="h-3 w-3" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Copy URL</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 shrink-0"
                          aria-label={`Open ${host.hostname} in new tab`}
                          onClick={() => window.open(url, '_blank')}
                        >
                          <ExternalLink className="h-3 w-3" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Open in new tab</TooltipContent>
                    </Tooltip>
                  </div>

                  {/* Actions */}
                  <div className="flex justify-end gap-2 pt-2 border-t">
                    {ttl && ttl.text !== 'Expired' && canCreate && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={extendMutation.isPending}
                        onClick={() => {
                          extendMutation.mutate(host.hostname, {
                            onSuccess: (data) => {
                              toast.success(`Extended TTL for ${host.hostname} (${data.ttl_hours}h)`)
                            },
                            onError: (err: any) => {
                              toast.error(err.response?.data?.detail || 'Failed to extend TTL')
                            },
                          })
                        }}
                      >
                        <TimerReset className="mr-2 h-4 w-4" />
                        Extend
                      </Button>
                    )}
                    {canDestroy && (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setDestroyHost(host)}
                      >
                        <Trash className="mr-2 h-4 w-4" />
                        Destroy
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open)
          if (!open) resetCreateDialog()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Personal Instance</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {/* Service selection */}
            <div className="space-y-2">
              <Label>Service</Label>
              <Select
                value={createService}
                onValueChange={(val) => {
                  setCreateService(val)
                  setCreateRegion('')
                  setCreateInputs({})
                }}
              >
                <SelectTrigger aria-label="Service">
                  <SelectValue placeholder="Select a service" />
                </SelectTrigger>
                <SelectContent>
                  {services.map((svc) => (
                    <SelectItem key={svc.service} value={svc.service}>
                      {svc.service}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Region selection (shows after service is picked) */}
            {createService && (
              <div className="space-y-2">
                <Label>Region</Label>
                <Select
                  value={createRegion || selectedConfig?.default_region || 'mel'}
                  onValueChange={setCreateRegion}
                >
                  <SelectTrigger aria-label="Region">
                    <SelectValue placeholder="Select a region" />
                  </SelectTrigger>
                  <SelectContent>
                    {REGIONS.map((r) => (
                      <SelectItem key={r.value} value={r.value}>
                        {r.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Dynamic required inputs */}
            {createService && selectedConfig?.required_inputs?.map((input) => (
              <div key={input.name} className="space-y-2">
                <Label>
                  {input.label}
                  {input.required !== false && <span className="text-red-500 ml-1">*</span>}
                </Label>
                {input.description && (
                  <p className="text-xs text-muted-foreground">{input.description}</p>
                )}
                <Input
                  type={input.type === 'password' ? 'password' : 'text'}
                  value={createInputs[input.name] || ''}
                  onChange={(e) =>
                    setCreateInputs((prev) => ({ ...prev, [input.name]: e.target.value }))
                  }
                  placeholder={input.label}
                  aria-required={input.required !== false}
                />
              </div>
            ))}

            {createService && (
              <p className="text-sm text-muted-foreground">
                A personal instance will be provisioned in the selected region.
                {selectedConfig?.default_ttl_hours
                  ? ` It will auto-expire after ${selectedConfig.default_ttl_hours} hours.`
                  : ''}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={createMutation.isPending || !createService}
            >
              {createMutation.isPending ? 'Creating...' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Destroy Confirmation */}
      <ConfirmDialog
        open={!!destroyHost}
        onOpenChange={(open) => { if (!open) setDestroyHost(null) }}
        title="Destroy Instance"
        description={`This will permanently destroy "${destroyHost?.hostname}" and delete all data on it. This cannot be undone.`}
        confirmLabel="Destroy"
        variant="destructive"
        onConfirm={handleDestroy}
      />
    </div>
  )
}
