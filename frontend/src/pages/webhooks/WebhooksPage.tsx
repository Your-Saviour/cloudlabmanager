import { useState, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, MoreHorizontal, Pencil, Trash, Play, History, Copy, RefreshCw, Link2, X } from 'lucide-react'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { relativeTime } from '@/lib/utils'
import { PageHeader } from '@/components/shared/PageHeader'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { DataTable } from '@/components/data/DataTable'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import type { WebhookEndpoint, Service } from '@/types'
import { useInventoryStore } from '@/stores/inventoryStore'

const SYSTEM_TASK_LABELS: Record<string, string> = {
  refresh_instances: 'Refresh Instances',
  refresh_costs: 'Refresh Costs',
}

const JOB_TYPE_LABELS: Record<string, string> = {
  service_script: 'Service Script',
  inventory_action: 'Inventory Action',
  system_task: 'System Task',
}

function webhookTargetSummary(w: WebhookEndpoint): string {
  switch (w.job_type) {
    case 'service_script':
      return `${w.service_name} → ${w.script_name}`
    case 'inventory_action':
      return `${w.type_slug} → ${w.action_name}`
    case 'system_task':
      return SYSTEM_TASK_LABELS[w.system_task || ''] || w.system_task || ''
    default:
      return w.job_type
  }
}

interface CreateForm {
  name: string
  description: string
  job_type: 'service_script' | 'inventory_action' | 'system_task' | ''
  service_name: string
  script_name: string
  type_slug: string
  action_name: string
  object_id: string
  system_task: string
  payload_mapping: Array<{ key: string; value: string }>
  is_enabled: boolean
}

const emptyForm: CreateForm = {
  name: '',
  description: '',
  job_type: '',
  service_name: '',
  script_name: '',
  type_slug: '',
  action_name: '',
  object_id: '',
  system_task: '',
  payload_mapping: [],
  is_enabled: true,
}

interface EditForm {
  name: string
  description: string
  payload_mapping: Array<{ key: string; value: string }>
  is_enabled: boolean
}

function mappingToArray(m: Record<string, string> | null): Array<{ key: string; value: string }> {
  if (!m) return []
  return Object.entries(m).map(([key, value]) => ({ key, value }))
}

function arrayToMapping(arr: Array<{ key: string; value: string }>): Record<string, string> | null {
  const filtered = arr.filter((r) => r.key.trim() !== '')
  if (filtered.length === 0) return null
  const obj: Record<string, string> = {}
  for (const r of filtered) obj[r.key.trim()] = r.value
  return obj
}

export default function WebhooksPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const serviceFilter = searchParams.get('service') || ''
  const canCreate = useHasPermission('webhooks.create')
  const canEdit = useHasPermission('webhooks.edit')
  const canDelete = useHasPermission('webhooks.delete')

  const inventoryTypes = useInventoryStore((s) => s.types)

  const [createOpen, setCreateOpen] = useState(false)
  const [editWebhook, setEditWebhook] = useState<WebhookEndpoint | null>(null)
  const [deleteWebhook, setDeleteWebhook] = useState<WebhookEndpoint | null>(null)
  const [historyWebhook, setHistoryWebhook] = useState<WebhookEndpoint | null>(null)
  const [tokenWebhook, setTokenWebhook] = useState<WebhookEndpoint | null>(null)
  const [regenerateConfirm, setRegenerateConfirm] = useState(false)
  const [createForm, setCreateForm] = useState<CreateForm>({ ...emptyForm })
  const [editForm, setEditForm] = useState<EditForm>({ name: '', description: '', payload_mapping: [], is_enabled: true })
  const [historyPage, setHistoryPage] = useState(1)

  // Data fetching
  const { data: webhooks = [], isLoading } = useQuery({
    queryKey: ['webhooks'],
    queryFn: async () => {
      const { data } = await api.get('/api/webhooks')
      return (data.webhooks || []) as WebhookEndpoint[]
    },
  })

  const { data: services = [] } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const { data } = await api.get('/api/services')
      return (data.services || []) as Service[]
    },
  })

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['webhook-history', historyWebhook?.id, historyPage],
    queryFn: async () => {
      const { data } = await api.get(`/api/webhooks/${historyWebhook!.id}/history`, {
        params: { page: historyPage, per_page: 20 },
      })
      return data as { webhook_id: number; webhook_name: string; total: number; page: number; per_page: number; jobs: Array<{ id: string; status: string; started_at: string; finished_at: string | null }> }
    },
    enabled: !!historyWebhook,
  })

  // Mutations
  const createMutation = useMutation({
    mutationFn: (body: CreateForm) => {
      const payload: Record<string, unknown> = {
        name: body.name,
        description: body.description || null,
        job_type: body.job_type,
        is_enabled: body.is_enabled,
        payload_mapping: arrayToMapping(body.payload_mapping),
      }
      if (body.job_type === 'service_script') {
        payload.service_name = body.service_name
        payload.script_name = body.script_name
      } else if (body.job_type === 'inventory_action') {
        payload.type_slug = body.type_slug
        payload.action_name = body.action_name
        if (body.object_id) payload.object_id = Number(body.object_id)
      } else if (body.job_type === 'system_task') {
        payload.system_task = body.system_task
      }
      return api.post('/api/webhooks', payload)
    },
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] })
      setCreateOpen(false)
      setCreateForm({ ...emptyForm })
      toast.success('Webhook created')
      // Show the token dialog with the newly created webhook (response is the webhook dict directly)
      const created = res.data as WebhookEndpoint
      if (created?.token) setTokenWebhook(created)
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Create failed'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: EditForm }) =>
      api.put(`/api/webhooks/${id}`, {
        name: body.name,
        description: body.description || null,
        payload_mapping: arrayToMapping(body.payload_mapping),
        is_enabled: body.is_enabled,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] })
      setEditWebhook(null)
      toast.success('Webhook updated')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Update failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/webhooks/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] })
      setDeleteWebhook(null)
      toast.success('Webhook deleted')
    },
    onError: () => toast.error('Delete failed'),
  })

  const regenerateTokenMutation = useMutation({
    mutationFn: (id: number) => api.post(`/api/webhooks/${id}/regenerate-token`),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] })
      const updated = res.data as WebhookEndpoint
      if (updated?.token) setTokenWebhook(updated)
      setRegenerateConfirm(false)
      toast.success('Token regenerated')
    },
    onError: () => toast.error('Regenerate failed'),
  })

  const testTriggerMutation = useMutation({
    mutationFn: (webhookId: number) => api.post(`/api/webhooks/${webhookId}/test`),
    onSuccess: (res) => {
      const jobId = res.data?.job_id
      if (jobId) {
        toast.success(`Webhook triggered — Job #${jobId.slice(0, 8)} started`, {
          action: { label: 'View', onClick: () => navigate(`/jobs/${jobId}`) },
        })
      } else {
        toast.success('Webhook triggered')
      }
      queryClient.invalidateQueries({ queryKey: ['webhooks'] })
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Trigger failed'),
  })

  const openEditDialog = useCallback((w: WebhookEndpoint) => {
    setEditForm({
      name: w.name,
      description: w.description || '',
      payload_mapping: mappingToArray(w.payload_mapping),
      is_enabled: w.is_enabled,
    })
    setEditWebhook(w)
  }, [])

  // Filtered scripts for selected service
  const selectedService = services.find((s) => s.name === createForm.service_name)
  const scriptOptions = selectedService?.scripts || []

  // Filtered actions for selected inventory type
  const selectedType = inventoryTypes.find((t) => t.slug === createForm.type_slug)
  const actionOptions = selectedType?.actions || []

  const webhookUrl = (token: string) => `${window.location.origin}/api/webhooks/trigger/${token}`

  const copyToClipboard = useCallback((text: string) => {
    navigator.clipboard.writeText(text).then(
      () => toast.success('Copied to clipboard'),
      () => toast.error('Copy failed')
    )
  }, [])

  const columns = useMemo<ColumnDef<WebhookEndpoint>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => (
          <div>
            <span className="font-medium">{row.original.name}</span>
            {row.original.description && (
              <p className="text-xs text-muted-foreground truncate max-w-[200px]">{row.original.description}</p>
            )}
          </div>
        ),
      },
      {
        id: 'type',
        header: 'Type',
        cell: ({ row }) => (
          <Badge variant="outline">{JOB_TYPE_LABELS[row.original.job_type] || row.original.job_type}</Badge>
        ),
      },
      {
        id: 'target',
        header: 'Target',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">{webhookTargetSummary(row.original)}</span>
        ),
      },
      {
        accessorKey: 'is_enabled',
        header: 'Status',
        cell: ({ row }) => (
          <Badge variant={row.original.is_enabled ? 'success' : 'secondary'}>
            {row.original.is_enabled ? 'Enabled' : 'Disabled'}
          </Badge>
        ),
      },
      {
        accessorKey: 'trigger_count',
        header: 'Triggers',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">{row.original.trigger_count}</span>
        ),
      },
      {
        accessorKey: 'last_trigger_at',
        header: 'Last Triggered',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">
            {row.original.last_trigger_at ? relativeTime(row.original.last_trigger_at) : 'Never'}
          </span>
        ),
      },
      {
        id: 'last_status',
        header: 'Last Status',
        cell: ({ row }) => {
          const w = row.original
          if (!w.last_status) return <span className="text-muted-foreground text-xs">—</span>
          const variant = w.last_status === 'completed' ? 'success' : w.last_status === 'failed' ? 'destructive' : w.last_status === 'running' ? 'running' : 'secondary'
          return (
            <div className="flex items-center gap-2">
              <Badge variant={variant}>{w.last_status}</Badge>
              {w.last_job_id && (
                <button
                  className="text-xs text-primary hover:underline"
                  onClick={() => navigate(`/jobs/${w.last_job_id}`)}
                >
                  #{w.last_job_id.slice(0, 8)}
                </button>
              )}
            </div>
          )
        },
      },
      {
        id: 'actions',
        cell: ({ row }) => (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7">
                <MoreHorizontal className="h-4 w-4" />
                <span className="sr-only">Actions</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {canEdit && (
                <DropdownMenuItem onClick={() => openEditDialog(row.original)}>
                  <Pencil className="mr-2 h-3 w-3" /> Edit
                </DropdownMenuItem>
              )}
              {canEdit && (
                <DropdownMenuItem onClick={() => testTriggerMutation.mutate(row.original.id)}>
                  <Play className="mr-2 h-3 w-3" /> Test
                </DropdownMenuItem>
              )}
              {canEdit && (
                <DropdownMenuItem onClick={async () => {
                  try {
                    const { data } = await api.get(`/api/webhooks/${row.original.id}/token`)
                    copyToClipboard(webhookUrl(data.token))
                  } catch { toast.error('Failed to fetch token') }
                }}>
                  <Copy className="mr-2 h-3 w-3" /> Copy URL
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onClick={() => { setHistoryPage(1); setHistoryWebhook(row.original) }}>
                <History className="mr-2 h-3 w-3" /> View History
              </DropdownMenuItem>
              {canEdit && (
                <DropdownMenuItem onClick={async () => {
                  try {
                    const { data } = await api.get(`/api/webhooks/${row.original.id}/token`)
                    setTokenWebhook({ ...row.original, token: data.token })
                  } catch { toast.error('Failed to fetch token') }
                }}>
                  <Link2 className="mr-2 h-3 w-3" /> View Token
                </DropdownMenuItem>
              )}
              {canDelete && (
                <DropdownMenuItem className="text-destructive" onClick={() => setDeleteWebhook(row.original)}>
                  <Trash className="mr-2 h-3 w-3" /> Delete
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canEdit, canDelete, navigate, openEditDialog, testTriggerMutation.mutate, copyToClipboard]
  )

  const filteredWebhooks = serviceFilter
    ? webhooks.filter((w) => w.service_name === serviceFilter)
    : webhooks

  const isCreateValid =
    createForm.name.trim() !== '' &&
    createForm.job_type !== '' &&
    (createForm.job_type !== 'service_script' || (createForm.service_name && createForm.script_name)) &&
    (createForm.job_type !== 'inventory_action' || (createForm.type_slug && createForm.action_name)) &&
    (createForm.job_type !== 'system_task' || createForm.system_task)

  return (
    <div>
      <PageHeader title="Webhooks" description="Manage webhook endpoints that allow external systems to trigger actions">
        {canCreate && (
          <Button size="sm" onClick={() => { setCreateForm({ ...emptyForm }); setCreateOpen(true) }}>
            <Plus className="mr-2 h-4 w-4" /> Create Webhook
          </Button>
        )}
      </PageHeader>

      {serviceFilter && (
        <div className="mb-4">
          <Badge variant="secondary" className="gap-1.5">
            Service: {serviceFilter}
            <X
              className="h-3 w-3 cursor-pointer"
              role="button"
              aria-label={`Clear ${serviceFilter} filter`}
              onClick={() => {
                searchParams.delete('service')
                setSearchParams(searchParams)
              }}
            />
          </Badge>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : (
        <DataTable columns={columns} data={filteredWebhooks} searchKey="name" searchPlaceholder="Search webhooks..." />
      )}

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>Create Webhook</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input
                value={createForm.name}
                onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                placeholder="My webhook endpoint"
              />
            </div>

            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea
                value={createForm.description}
                onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                placeholder="Optional description..."
                rows={2}
              />
            </div>

            <div className="space-y-2">
              <Label>Job Type</Label>
              <Select
                value={createForm.job_type}
                onValueChange={(v) => setCreateForm({
                  ...createForm,
                  job_type: v as CreateForm['job_type'],
                  service_name: '',
                  script_name: '',
                  type_slug: '',
                  action_name: '',
                  object_id: '',
                  system_task: '',
                })}
              >
                <SelectTrigger><SelectValue placeholder="Select job type..." /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="service_script">Service Script</SelectItem>
                  <SelectItem value="inventory_action">Inventory Action</SelectItem>
                  <SelectItem value="system_task">System Task</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Service Script fields */}
            {createForm.job_type === 'service_script' && (
              <>
                <div className="space-y-2">
                  <Label>Service</Label>
                  <Select
                    value={createForm.service_name}
                    onValueChange={(v) => setCreateForm({ ...createForm, service_name: v, script_name: '' })}
                  >
                    <SelectTrigger><SelectValue placeholder="Select service..." /></SelectTrigger>
                    <SelectContent>
                      {services.map((s) => (
                        <SelectItem key={s.name} value={s.name}>{s.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Script</Label>
                  <Select
                    value={createForm.script_name}
                    onValueChange={(v) => setCreateForm({ ...createForm, script_name: v })}
                  >
                    <SelectTrigger><SelectValue placeholder="Select script..." /></SelectTrigger>
                    <SelectContent>
                      {scriptOptions.map((s) => (
                        <SelectItem key={s.name} value={s.name}>{s.label || s.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}

            {/* Inventory Action fields */}
            {createForm.job_type === 'inventory_action' && (
              <>
                <div className="space-y-2">
                  <Label>Inventory Type</Label>
                  <Select
                    value={createForm.type_slug}
                    onValueChange={(v) => setCreateForm({ ...createForm, type_slug: v, action_name: '' })}
                  >
                    <SelectTrigger><SelectValue placeholder="Select type..." /></SelectTrigger>
                    <SelectContent>
                      {inventoryTypes.map((t) => (
                        <SelectItem key={t.slug} value={t.slug}>{t.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Action</Label>
                  <Select
                    value={createForm.action_name}
                    onValueChange={(v) => setCreateForm({ ...createForm, action_name: v })}
                  >
                    <SelectTrigger><SelectValue placeholder="Select action..." /></SelectTrigger>
                    <SelectContent>
                      {actionOptions.map((a) => (
                        <SelectItem key={a.name} value={a.name}>{a.label || a.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}

            {/* System Task field */}
            {createForm.job_type === 'system_task' && (
              <div className="space-y-2">
                <Label>Task</Label>
                <Select
                  value={createForm.system_task}
                  onValueChange={(v) => setCreateForm({ ...createForm, system_task: v })}
                >
                  <SelectTrigger><SelectValue placeholder="Select task..." /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="refresh_instances">Refresh Instances</SelectItem>
                    <SelectItem value="refresh_costs">Refresh Costs</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Payload Mapping */}
            {createForm.job_type && (
              <div className="space-y-2">
                <Label>Payload Mapping</Label>
                <p className="text-xs text-muted-foreground">
                  Map fields from the incoming webhook JSON body to script inputs
                </p>
                <div className="space-y-2">
                  {createForm.payload_mapping.map((row, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Input
                        value={row.key}
                        onChange={(e) => {
                          const updated = [...createForm.payload_mapping]
                          updated[i] = { ...updated[i], key: e.target.value }
                          setCreateForm({ ...createForm, payload_mapping: updated })
                        }}
                        placeholder="Input name"
                        className="flex-1"
                      />
                      <span className="text-muted-foreground text-sm">→</span>
                      <Input
                        value={row.value}
                        onChange={(e) => {
                          const updated = [...createForm.payload_mapping]
                          updated[i] = { ...updated[i], value: e.target.value }
                          setCreateForm({ ...createForm, payload_mapping: updated })
                        }}
                        placeholder="$.path.to.value"
                        className="flex-1 font-mono text-sm"
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 shrink-0"
                        onClick={() => {
                          const updated = createForm.payload_mapping.filter((_, idx) => idx !== i)
                          setCreateForm({ ...createForm, payload_mapping: updated })
                        }}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCreateForm({ ...createForm, payload_mapping: [...createForm.payload_mapping, { key: '', value: '' }] })}
                  >
                    <Plus className="mr-1 h-3 w-3" /> Add Mapping
                  </Button>
                </div>
              </div>
            )}

            <div className="flex items-center gap-2">
              <Switch
                id="create-enabled"
                checked={createForm.is_enabled}
                onCheckedChange={(v) => setCreateForm({ ...createForm, is_enabled: v })}
              />
              <Label htmlFor="create-enabled" className="text-sm font-normal">Enabled</Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button
              onClick={() => createMutation.mutate(createForm)}
              disabled={!isCreateValid || createMutation.isPending}
            >
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editWebhook} onOpenChange={() => setEditWebhook(null)}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>Edit Webhook — {editWebhook?.name}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            {/* Read-only target info */}
            {editWebhook && (
              <div className="rounded-md border border-border bg-muted/50 p-3 space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Target (read-only)</p>
                <p className="text-sm">{JOB_TYPE_LABELS[editWebhook.job_type]} — {webhookTargetSummary(editWebhook)}</p>
              </div>
            )}

            <div className="space-y-2">
              <Label>Name</Label>
              <Input
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea
                value={editForm.description}
                onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                rows={2}
              />
            </div>

            {/* Payload Mapping */}
            <div className="space-y-2">
              <Label>Payload Mapping</Label>
              <p className="text-xs text-muted-foreground">
                Map fields from the incoming webhook JSON body to script inputs
              </p>
              <div className="space-y-2">
                {editForm.payload_mapping.map((row, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Input
                      value={row.key}
                      onChange={(e) => {
                        const updated = [...editForm.payload_mapping]
                        updated[i] = { ...updated[i], key: e.target.value }
                        setEditForm({ ...editForm, payload_mapping: updated })
                      }}
                      placeholder="Input name"
                      className="flex-1"
                    />
                    <span className="text-muted-foreground text-sm">→</span>
                    <Input
                      value={row.value}
                      onChange={(e) => {
                        const updated = [...editForm.payload_mapping]
                        updated[i] = { ...updated[i], value: e.target.value }
                        setEditForm({ ...editForm, payload_mapping: updated })
                      }}
                      placeholder="$.path.to.value"
                      className="flex-1 font-mono text-sm"
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0"
                      onClick={() => {
                        const updated = editForm.payload_mapping.filter((_, idx) => idx !== i)
                        setEditForm({ ...editForm, payload_mapping: updated })
                      }}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setEditForm({ ...editForm, payload_mapping: [...editForm.payload_mapping, { key: '', value: '' }] })}
                >
                  <Plus className="mr-1 h-3 w-3" /> Add Mapping
                </Button>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Switch
                id="edit-enabled"
                checked={editForm.is_enabled}
                onCheckedChange={(v) => setEditForm({ ...editForm, is_enabled: v })}
              />
              <Label htmlFor="edit-enabled" className="text-sm font-normal">Enabled</Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setEditWebhook(null)}>Cancel</Button>
            <Button
              onClick={() => editWebhook && updateMutation.mutate({ id: editWebhook.id, body: editForm })}
              disabled={!editForm.name.trim() || updateMutation.isPending}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Token/URL Display Dialog */}
      <Dialog open={!!tokenWebhook} onOpenChange={() => { setTokenWebhook(null); setRegenerateConfirm(false) }}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>Webhook URL — {tokenWebhook?.name}</DialogTitle></DialogHeader>
          {tokenWebhook && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Webhook URL</Label>
                <div className="flex items-center gap-2">
                  <Input
                    readOnly
                    value={webhookUrl(tokenWebhook.token)}
                    className="font-mono text-xs"
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    className="shrink-0"
                    onClick={() => copyToClipboard(webhookUrl(tokenWebhook.token))}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              <div className="rounded-md border border-amber-500/30 bg-amber-500/15 p-3">
                <p className="text-xs text-amber-400">
                  Keep this URL secret. Anyone with this URL can trigger this webhook.
                </p>
              </div>

              {canEdit && (
                <div>
                  {regenerateConfirm ? (
                    <div className="flex items-center gap-2">
                      <p className="text-xs text-muted-foreground flex-1">
                        This will invalidate the current URL. Are you sure?
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setRegenerateConfirm(false)}
                      >
                        Cancel
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => regenerateTokenMutation.mutate(tokenWebhook.id)}
                        disabled={regenerateTokenMutation.isPending}
                      >
                        Confirm
                      </Button>
                    </div>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setRegenerateConfirm(true)}
                    >
                      <RefreshCw className="mr-2 h-3 w-3" /> Regenerate Token
                    </Button>
                  )}
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* History Dialog */}
      <Dialog open={!!historyWebhook} onOpenChange={() => setHistoryWebhook(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Execution History: {historyWebhook?.name}</DialogTitle>
          </DialogHeader>
          {historyLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-8 w-full" />)}
            </div>
          ) : historyData && historyData.jobs.length > 0 ? (
            <>
              <div className="rounded-md border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/50">
                      <th className="px-3 py-2 text-left font-medium">Job ID</th>
                      <th className="px-3 py-2 text-left font-medium">Status</th>
                      <th className="px-3 py-2 text-left font-medium">Started</th>
                      <th className="px-3 py-2 text-left font-medium">Finished</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyData.jobs.map((j) => (
                      <tr key={j.id} className="border-b last:border-0">
                        <td className="px-3 py-2">
                          <button
                            className="text-primary hover:underline font-mono text-xs"
                            onClick={() => { setHistoryWebhook(null); navigate(`/jobs/${j.id}`) }}
                          >
                            #{j.id}
                          </button>
                        </td>
                        <td className="px-3 py-2">
                          <Badge variant={j.status === 'completed' ? 'success' : j.status === 'failed' ? 'destructive' : j.status === 'running' ? 'running' : 'secondary'}>
                            {j.status}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-muted-foreground text-xs">
                          {j.started_at ? relativeTime(j.started_at) : '—'}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground text-xs">
                          {j.finished_at ? relativeTime(j.finished_at) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Pagination */}
              {historyData.total > historyData.per_page && (
                <div className="flex items-center justify-between pt-2">
                  <p className="text-xs text-muted-foreground">
                    Page {historyData.page} of {Math.ceil(historyData.total / historyData.per_page)}
                    {' '}({historyData.total} total)
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={historyPage <= 1}
                      onClick={() => setHistoryPage((p) => p - 1)}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={historyPage >= Math.ceil(historyData.total / historyData.per_page)}
                      onClick={() => setHistoryPage((p) => p + 1)}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground py-4 text-center">No executions yet.</p>
          )}
        </DialogContent>
      </Dialog>

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteWebhook}
        onOpenChange={() => setDeleteWebhook(null)}
        title="Delete Webhook"
        description={`Permanently delete webhook "${deleteWebhook?.name}"? Any external systems using this webhook URL will stop working.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteWebhook && deleteMutation.mutate(deleteWebhook.id)}
      />
    </div>
  )
}
