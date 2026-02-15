import { useState, useMemo, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, MoreHorizontal, Pencil, Trash, Play, Pause, History, X } from 'lucide-react'
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
import { Checkbox } from '@/components/ui/checkbox'
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
import type { ScheduledJob, CronPreview, Service, InventoryType } from '@/types'
import { useInventoryStore } from '@/stores/inventoryStore'

const SYSTEM_TASK_LABELS: Record<string, string> = {
  refresh_instances: 'Refresh Instances',
  refresh_costs: 'Refresh Costs',
}

function jobTypeSummary(s: ScheduledJob): string {
  switch (s.job_type) {
    case 'service_script':
      return `${s.service_name} / ${s.script_name}`
    case 'inventory_action':
      return `${s.type_slug}.${s.action_name}`
    case 'system_task':
      return SYSTEM_TASK_LABELS[s.system_task || ''] || s.system_task || ''
    default:
      return s.job_type
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
  cron_expression: string
  is_enabled: boolean
  skip_if_running: boolean
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
  cron_expression: '',
  is_enabled: true,
  skip_if_running: true,
}

interface EditForm {
  name: string
  description: string
  cron_expression: string
  is_enabled: boolean
  skip_if_running: boolean
}

export default function SchedulesPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const serviceFilter = searchParams.get('service') || ''
  const canCreate = useHasPermission('schedules.create')
  const canEdit = useHasPermission('schedules.edit')
  const canDelete = useHasPermission('schedules.delete')

  const inventoryTypes = useInventoryStore((s) => s.types)

  const [createOpen, setCreateOpen] = useState(false)
  const [editSchedule, setEditSchedule] = useState<ScheduledJob | null>(null)
  const [deleteSchedule, setDeleteSchedule] = useState<ScheduledJob | null>(null)
  const [historySchedule, setHistorySchedule] = useState<ScheduledJob | null>(null)
  const [createForm, setCreateForm] = useState<CreateForm>({ ...emptyForm })
  const [editForm, setEditForm] = useState<EditForm>({ name: '', description: '', cron_expression: '', is_enabled: true, skip_if_running: true })

  // Cron preview state
  const [cronInput, setCronInput] = useState('')
  const [debouncedCron, setDebouncedCron] = useState('')

  // Debounce cron input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedCron(cronInput), 300)
    return () => clearTimeout(timer)
  }, [cronInput])

  const { data: schedules = [], isLoading } = useQuery({
    queryKey: ['schedules'],
    queryFn: async () => {
      const { data } = await api.get('/api/schedules')
      return (data.schedules || []) as ScheduledJob[]
    },
  })

  const { data: services = [] } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const { data } = await api.get('/api/services')
      return (data.services || []) as Service[]
    },
  })

  const { data: cronPreview } = useQuery({
    queryKey: ['cron-preview', debouncedCron],
    queryFn: async () => {
      const { data } = await api.get('/api/schedules/preview', { params: { expression: debouncedCron, count: 5 } })
      return data as CronPreview
    },
    enabled: debouncedCron.trim().length > 0,
    retry: false,
  })

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['schedule-history', historySchedule?.id],
    queryFn: async () => {
      const { data } = await api.get(`/api/schedules/${historySchedule!.id}/history`)
      return data as { schedule_id: number; schedule_name: string; total: number; jobs: Array<{ id: string; status: string; started_at: string; finished_at: string | null; username: string }> }
    },
    enabled: !!historySchedule,
  })

  const createMutation = useMutation({
    mutationFn: (body: CreateForm) => {
      const payload: Record<string, unknown> = {
        name: body.name,
        description: body.description || null,
        job_type: body.job_type,
        cron_expression: body.cron_expression,
        is_enabled: body.is_enabled,
        skip_if_running: body.skip_if_running,
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
      return api.post('/api/schedules', payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] })
      setCreateOpen(false)
      setCreateForm({ ...emptyForm })
      setCronInput('')
      toast.success('Schedule created')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Create failed'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: EditForm }) =>
      api.put(`/api/schedules/${id}`, {
        name: body.name,
        description: body.description || null,
        cron_expression: body.cron_expression,
        is_enabled: body.is_enabled,
        skip_if_running: body.skip_if_running,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] })
      setEditSchedule(null)
      toast.success('Schedule updated')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Update failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/schedules/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] })
      setDeleteSchedule(null)
      toast.success('Schedule deleted')
    },
    onError: () => toast.error('Delete failed'),
  })

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_enabled }: { id: number; is_enabled: boolean }) =>
      api.put(`/api/schedules/${id}`, { is_enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] })
      toast.success('Schedule updated')
    },
    onError: () => toast.error('Update failed'),
  })

  const openEditDialog = useCallback((s: ScheduledJob) => {
    setEditForm({
      name: s.name,
      description: s.description || '',
      cron_expression: s.cron_expression,
      is_enabled: s.is_enabled,
      skip_if_running: s.skip_if_running,
    })
    setCronInput(s.cron_expression)
    setEditSchedule(s)
  }, [])

  // Filtered scripts for selected service
  const selectedService = services.find((s) => s.name === createForm.service_name)
  const scriptOptions = selectedService?.scripts || []

  // Filtered actions for selected inventory type
  const selectedType = inventoryTypes.find((t) => t.slug === createForm.type_slug)
  const actionOptions = selectedType?.actions || []

  const columns = useMemo<ColumnDef<ScheduledJob>[]>(
    () => [
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
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
      },
      {
        id: 'type',
        header: 'Type',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">{jobTypeSummary(row.original)}</span>
        ),
      },
      {
        accessorKey: 'cron_expression',
        header: 'Schedule',
        cell: ({ row }) => (
          <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{row.original.cron_expression}</code>
        ),
      },
      {
        accessorKey: 'last_run_at',
        header: 'Last Run',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">
            {row.original.last_run_at ? relativeTime(row.original.last_run_at) : '—'}
          </span>
        ),
      },
      {
        accessorKey: 'next_run_at',
        header: 'Next Run',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">
            {row.original.next_run_at ? relativeTime(row.original.next_run_at) : '—'}
          </span>
        ),
      },
      {
        id: 'last_status',
        header: 'Last Status',
        cell: ({ row }) => {
          const s = row.original
          if (!s.last_status) return <span className="text-muted-foreground text-xs">—</span>
          const variant = s.last_status === 'completed' ? 'success' : s.last_status === 'failed' ? 'destructive' : s.last_status === 'running' ? 'running' : 'secondary'
          return (
            <div className="flex items-center gap-2">
              <Badge variant={variant}>{s.last_status}</Badge>
              {s.last_job_id && (
                <button
                  className="text-xs text-primary hover:underline"
                  onClick={() => navigate(`/jobs/${s.last_job_id}`)}
                >
                  #{s.last_job_id.slice(0, 8)}
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
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setHistorySchedule(row.original)}>
                <History className="mr-2 h-3 w-3" /> View History
              </DropdownMenuItem>
              {canEdit && (
                <DropdownMenuItem onClick={() => openEditDialog(row.original)}>
                  <Pencil className="mr-2 h-3 w-3" /> Edit
                </DropdownMenuItem>
              )}
              {canEdit && (
                <DropdownMenuItem
                  onClick={() => toggleMutation.mutate({ id: row.original.id, is_enabled: !row.original.is_enabled })}
                >
                  {row.original.is_enabled ? (
                    <><Pause className="mr-2 h-3 w-3" /> Disable</>
                  ) : (
                    <><Play className="mr-2 h-3 w-3" /> Enable</>
                  )}
                </DropdownMenuItem>
              )}
              {canDelete && (
                <DropdownMenuItem className="text-destructive" onClick={() => setDeleteSchedule(row.original)}>
                  <Trash className="mr-2 h-3 w-3" /> Delete
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    [canEdit, canDelete, navigate, openEditDialog, toggleMutation]
  )

  const filteredSchedules = serviceFilter
    ? schedules.filter((s) => s.service_name === serviceFilter)
    : schedules

  const isCreateValid =
    createForm.name.trim() !== '' &&
    createForm.job_type !== '' &&
    createForm.cron_expression.trim() !== '' &&
    (createForm.job_type !== 'service_script' || (createForm.service_name && createForm.script_name)) &&
    (createForm.job_type !== 'inventory_action' || (createForm.type_slug && createForm.action_name)) &&
    (createForm.job_type !== 'system_task' || createForm.system_task)

  return (
    <div>
      <PageHeader title="Schedules" description="Manage scheduled jobs and automation">
        {canCreate && (
          <Button size="sm" onClick={() => { setCreateForm({ ...emptyForm }); setCronInput(''); setCreateOpen(true) }}>
            <Plus className="mr-2 h-4 w-4" /> Create Schedule
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
        <DataTable columns={columns} data={filteredSchedules} searchKey="name" searchPlaceholder="Search schedules..." />
      )}

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>Create Schedule</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input
                value={createForm.name}
                onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                placeholder="My scheduled job"
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

            <div className="space-y-2">
              <Label>Cron Expression</Label>
              <Input
                value={createForm.cron_expression}
                onChange={(e) => {
                  setCreateForm({ ...createForm, cron_expression: e.target.value })
                  setCronInput(e.target.value)
                }}
                placeholder="0 */6 * * *"
                className="font-mono"
              />
              <p className="text-xs text-muted-foreground">
                Format: minute hour day month weekday (e.g., "0 */6 * * *" = every 6 hours)
              </p>
              {cronPreview && cronInput === createForm.cron_expression && cronPreview.next_runs.length > 0 && (
                <div className="rounded-md border border-border bg-muted/50 p-3 space-y-1">
                  <p className="text-xs font-medium text-muted-foreground">Next runs:</p>
                  {cronPreview.next_runs.map((t, i) => (
                    <p key={i} className="text-xs text-foreground font-mono">
                      {new Date(t).toLocaleString()}
                    </p>
                  ))}
                </div>
              )}
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="create-skip"
                  checked={createForm.skip_if_running}
                  onCheckedChange={(v) => setCreateForm({ ...createForm, skip_if_running: !!v })}
                />
                <Label htmlFor="create-skip" className="text-sm font-normal">Skip if already running</Label>
              </div>
            </div>

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
      <Dialog open={!!editSchedule} onOpenChange={() => setEditSchedule(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>Edit Schedule — {editSchedule?.name}</DialogTitle></DialogHeader>
          <div className="space-y-4">
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

            <div className="space-y-2">
              <Label>Cron Expression</Label>
              <Input
                value={editForm.cron_expression}
                onChange={(e) => {
                  setEditForm({ ...editForm, cron_expression: e.target.value })
                  setCronInput(e.target.value)
                }}
                className="font-mono"
              />
              <p className="text-xs text-muted-foreground">
                Format: minute hour day month weekday (e.g., "0 */6 * * *" = every 6 hours)
              </p>
              {cronPreview && cronInput === editForm.cron_expression && cronPreview.next_runs.length > 0 && (
                <div className="rounded-md border border-border bg-muted/50 p-3 space-y-1">
                  <p className="text-xs font-medium text-muted-foreground">Next runs:</p>
                  {cronPreview.next_runs.map((t, i) => (
                    <p key={i} className="text-xs text-foreground font-mono">
                      {new Date(t).toLocaleString()}
                    </p>
                  ))}
                </div>
              )}
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="edit-skip"
                  checked={editForm.skip_if_running}
                  onCheckedChange={(v) => setEditForm({ ...editForm, skip_if_running: !!v })}
                />
                <Label htmlFor="edit-skip" className="text-sm font-normal">Skip if already running</Label>
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
            <Button variant="outline" onClick={() => setEditSchedule(null)}>Cancel</Button>
            <Button
              onClick={() => editSchedule && updateMutation.mutate({ id: editSchedule.id, body: editForm })}
              disabled={!editForm.name.trim() || !editForm.cron_expression.trim() || updateMutation.isPending}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* History Dialog */}
      <Dialog open={!!historySchedule} onOpenChange={() => setHistorySchedule(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Execution History: {historySchedule?.name}</DialogTitle>
          </DialogHeader>
          {historyLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-8 w-full" />)}
            </div>
          ) : historyData && historyData.jobs.length > 0 ? (
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
                          onClick={() => { setHistorySchedule(null); navigate(`/jobs/${j.id}`) }}
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
          ) : (
            <p className="text-sm text-muted-foreground py-4 text-center">No executions yet.</p>
          )}
        </DialogContent>
      </Dialog>

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteSchedule}
        onOpenChange={() => setDeleteSchedule(null)}
        title="Delete Schedule"
        description={`Permanently delete schedule "${deleteSchedule?.name}"?`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteSchedule && deleteMutation.mutate(deleteSchedule.id)}
      />
    </div>
  )
}
