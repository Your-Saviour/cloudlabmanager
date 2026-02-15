import { useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Trash2, Play, Plus, X, Terminal } from 'lucide-react'
import api from '@/lib/api'
import { useInventoryStore } from '@/stores/inventoryStore'
import { useHasPermission } from '@/lib/permissions'
import { PageHeader } from '@/components/shared/PageHeader'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { toast } from 'sonner'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { DataTable } from '@/components/data/DataTable'
import { relativeTime } from '@/lib/utils'
import type { ColumnDef } from '@tanstack/react-table'
import type { InventoryObject, InventoryField, Tag, ACLEntry, Job } from '@/types'

export default function InventoryDetailPage() {
  const { typeSlug, objId } = useParams<{ typeSlug: string; objId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const types = useInventoryStore((s) => s.types)
  const typeConfig = types.find((t) => t.slug === typeSlug)
  const canEdit = useHasPermission(`inventory.${typeSlug}.edit`)
  const canDelete = useHasPermission(`inventory.${typeSlug}.delete`)

  const [editing, setEditing] = useState(false)
  const [formData, setFormData] = useState<Record<string, unknown>>({})
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [actionConfirm, setActionConfirm] = useState<string | null>(null)

  const { data: obj, isLoading } = useQuery({
    queryKey: ['inventory', typeSlug, objId],
    queryFn: async () => {
      const { data } = await api.get(`/api/inventory/${typeSlug}/${objId}`)
      return data as InventoryObject
    },
    enabled: !!typeSlug && !!objId,
  })

  const { data: tags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/tags')
      return (data.tags || []) as Tag[]
    },
  })

  const { data: acl = [] } = useQuery({
    queryKey: ['inventory', typeSlug, objId, 'acl'],
    queryFn: async () => {
      const { data } = await api.get(`/api/inventory/${typeSlug}/${objId}/acl`)
      return (data.acl || []) as ACLEntry[]
    },
    enabled: !!typeSlug && !!objId,
  })

  const { data: jobHistory = [], isLoading: jobsLoading } = useQuery({
    queryKey: ['inventory', typeSlug, objId, 'jobs'],
    queryFn: async () => {
      const { data } = await api.get(`/api/jobs?object_id=${objId}`)
      return (data.jobs || []) as Job[]
    },
    enabled: !!objId,
    refetchInterval: 10000,
  })

  const lastJob = jobHistory.length > 0 ? jobHistory[0] : null

  const jobColumns = useMemo<ColumnDef<Job>[]>(
    () => [
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: 'action',
        header: 'Action',
        cell: ({ row }) => (
          <button
            type="button"
            className="text-primary hover:underline font-medium"
            onClick={() => navigate(`/jobs/${row.original.id}`)}
            aria-label={`View job: ${row.original.action}`}
          >
            {row.original.action}
          </button>
        ),
      },
      {
        accessorKey: 'username',
        header: 'Triggered By',
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.started_by || row.original.username || '-'}
          </span>
        ),
      },
      {
        accessorKey: 'started_at',
        header: 'Started',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">
            {relativeTime(row.original.started_at)}
          </span>
        ),
      },
      {
        id: 'duration',
        header: 'Duration',
        cell: ({ row }) => {
          const { started_at, finished_at, status } = row.original
          if (status === 'running') {
            return <span className="text-muted-foreground text-xs">running</span>
          }
          if (!started_at || !finished_at) {
            return <span className="text-muted-foreground text-xs">-</span>
          }
          const ms = new Date(finished_at).getTime() - new Date(started_at).getTime()
          const secs = Math.floor(ms / 1000)
          if (secs < 60) return <span className="text-muted-foreground text-xs">{secs}s</span>
          const mins = Math.floor(secs / 60)
          const remSecs = secs % 60
          return <span className="text-muted-foreground text-xs">{mins}m {remSecs}s</span>
        },
      },
    ],
    [navigate]
  )

  const updateMutation = useMutation({
    mutationFn: (body: { name?: string; data?: Record<string, unknown> }) =>
      api.put(`/api/inventory/${typeSlug}/${objId}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['inventory', typeSlug, objId] })
      setEditing(false)
      toast.success('Updated successfully')
    },
    onError: () => toast.error('Update failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.delete(`/api/inventory/${typeSlug}/${objId}`),
    onSuccess: () => {
      toast.success('Deleted')
      navigate(`/inventory/${typeSlug}`)
    },
    onError: () => toast.error('Delete failed'),
  })

  const addTagMutation = useMutation({
    mutationFn: (tagId: number) =>
      api.post(`/api/inventory/${typeSlug}/${objId}/tags`, { tag_ids: [tagId] }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inventory', typeSlug, objId] }),
  })

  const removeTagMutation = useMutation({
    mutationFn: (tagId: number) => api.delete(`/api/inventory/${typeSlug}/${objId}/tags/${tagId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inventory', typeSlug, objId] }),
  })

  const actionMutation = useMutation({
    mutationFn: (actionName: string) =>
      api.post(`/api/inventory/${typeSlug}/${objId}/actions/${actionName}`),
    onSuccess: (res) => {
      setActionConfirm(null)
      if (res.data.job_id) {
        toast.success('Action started')
        navigate(`/jobs/${res.data.job_id}`)
      } else {
        toast.success('Action completed')
      }
    },
    onError: () => toast.error('Action failed'),
  })

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (!obj) return <div className="text-muted-foreground">Object not found</div>

  const startEdit = () => {
    setFormData({ name: obj.name, ...obj.data })
    setEditing(true)
  }

  const saveEdit = () => {
    const { name, ...data } = formData
    updateMutation.mutate({ name: name as string, data })
  }

  const availableTags = tags.filter((t) => !obj.tags.some((ot) => ot.id === t.id))

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="icon" onClick={() => navigate(`/inventory/${typeSlug}`)} aria-label="Back to inventory list">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">{obj.name}</h1>
          <p className="text-sm text-muted-foreground">{typeConfig?.label || typeSlug}</p>
        </div>
        <div className="flex gap-2 items-center">
          {lastJob && (
            <button
              type="button"
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => navigate(`/jobs/${lastJob.id}`)}
              title={`Last job: ${lastJob.action} — ${lastJob.status}`}
              aria-label={`Last job: ${lastJob.action}, status ${lastJob.status}, ${relativeTime(lastJob.started_at)}`}
            >
              <StatusBadge status={lastJob.status} />
              <span>{relativeTime(lastJob.started_at)}</span>
            </button>
          )}
          {canEdit && !editing && (
            <Button variant="outline" size="sm" onClick={startEdit}>Edit</Button>
          )}
          {canDelete && (
            <Button variant="outline" size="sm" className="text-destructive" onClick={() => setDeleteOpen(true)}>
              <Trash2 className="mr-2 h-3 w-3" /> Delete
            </Button>
          )}
        </div>
      </div>

      <Tabs defaultValue="details">
        <TabsList>
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="tags">Tags</TabsTrigger>
          <TabsTrigger value="actions">Actions</TabsTrigger>
          <TabsTrigger value="acl">ACL</TabsTrigger>
          <TabsTrigger value="jobs">Job History</TabsTrigger>
        </TabsList>

        <TabsContent value="details" className="mt-4">
          <Card>
            <CardContent className="pt-6 space-y-4">
              {editing ? (
                <>
                  <div className="space-y-2">
                    <Label>Name</Label>
                    <Input
                      value={(formData.name as string) || ''}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    />
                  </div>
                  {typeConfig?.fields.map((field) => (
                    <FieldEditor key={field.name} field={field} formData={formData} setFormData={setFormData} />
                  ))}
                  <div className="flex gap-2 pt-2">
                    <Button onClick={saveEdit} disabled={updateMutation.isPending}>Save</Button>
                    <Button variant="outline" onClick={() => setEditing(false)}>Cancel</Button>
                  </div>
                </>
              ) : (
                <>
                  <div className="grid gap-3">
                    <div>
                      <p className="text-xs text-muted-foreground uppercase tracking-wider">Name</p>
                      <p className="text-sm mt-1">{obj.name}</p>
                    </div>
                    {typeConfig?.fields.map((field) => {
                      const val = obj.data[field.name]
                      if (field.type === 'secret') return (
                        <div key={field.name}>
                          <p className="text-xs text-muted-foreground uppercase tracking-wider">{field.label || field.name}</p>
                          <p className="text-sm mt-1 font-mono">{'*'.repeat(8)}</p>
                        </div>
                      )
                      return (
                        <div key={field.name}>
                          <p className="text-xs text-muted-foreground uppercase tracking-wider">{field.label || field.name}</p>
                          <p className="text-sm mt-1 font-mono whitespace-pre-wrap">
                            {val != null ? (typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val)) : '-'}
                          </p>
                        </div>
                      )
                    })}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tags" className="mt-4">
          <Card>
            <CardContent className="pt-6">
              <div className="flex flex-wrap gap-2 mb-4">
                {obj.tags.map((tag) => (
                  <Badge key={tag.id} variant="outline" className="gap-1" style={{ borderColor: tag.color, color: tag.color }}>
                    {tag.name}
                    {canEdit && (
                      <button onClick={() => removeTagMutation.mutate(tag.id)}>
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </Badge>
                ))}
              </div>
              {canEdit && availableTags.length > 0 && (
                <Select onValueChange={(val) => addTagMutation.mutate(Number(val))}>
                  <SelectTrigger className="w-48">
                    <SelectValue placeholder="Add tag..." />
                  </SelectTrigger>
                  <SelectContent>
                    {availableTags.map((t) => (
                      <SelectItem key={t.id} value={String(t.id)}>{t.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="actions" className="mt-4">
          <Card>
            <CardContent className="pt-6">
              {typeConfig?.actions.filter((a) => a.scope === 'object').length === 0 ? (
                <p className="text-sm text-muted-foreground">No actions available for this type.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {typeConfig?.actions
                    .filter((a) => a.scope === 'object')
                    .map((action) => {
                      // SSH builtin action navigates to terminal
                      if (action.type === 'builtin' && action.name === 'ssh') {
                        const hostname = obj?.data.hostname as string | undefined
                        const ip = obj?.data.ip_address as string | undefined
                        const isRunning = obj?.data.power_status === 'running'
                        if (!isRunning || !hostname) return null
                        return (
                          <Button
                            key={action.name}
                            variant="outline"
                            size="sm"
                            onClick={() => navigate(`/ssh/${hostname}/${ip || hostname}`)}
                          >
                            <Terminal className="mr-2 h-3 w-3" /> {action.label}
                          </Button>
                        )
                      }
                      const isDestructive = action.destructive || action.name === 'destroy'
                      return (
                        <Button
                          key={action.name}
                          variant={isDestructive ? "destructive" : "outline"}
                          size="sm"
                          onClick={() => (action.confirm || isDestructive) ? setActionConfirm(action.name) : actionMutation.mutate(action.name)}
                        >
                          {isDestructive ? <Trash2 className="mr-2 h-3 w-3" /> : <Play className="mr-2 h-3 w-3" />} {action.label}
                        </Button>
                      )
                    })}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="acl" className="mt-4">
          <Card>
            <CardContent className="pt-6">
              {acl.length === 0 ? (
                <p className="text-sm text-muted-foreground">No ACL rules configured.</p>
              ) : (
                <div className="space-y-2">
                  {acl.map((entry) => (
                    <div key={entry.id} className="flex items-center justify-between px-3 py-2 rounded-md bg-muted/30">
                      <span className="text-sm font-medium">{entry.username}</span>
                      <Badge variant="outline">{entry.permission}</Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="jobs" className="mt-4">
          <Card>
            <CardContent className="pt-6">
              {jobsLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : jobHistory.length === 0 ? (
                <p className="text-sm text-muted-foreground">No jobs have been run against this object.</p>
              ) : (
                <DataTable
                  columns={jobColumns}
                  data={jobHistory}
                  searchKey="action"
                  searchPlaceholder="Search jobs..."
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Delete confirm */}
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete Object"
        description={`Permanently delete "${obj.name}"?`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteMutation.mutate()}
      />

      {/* Action confirm */}
      {(() => {
        const confirmAction = typeConfig?.actions.find((a) => a.name === actionConfirm)
        const isDestructive = confirmAction?.destructive || confirmAction?.name === 'destroy'
        return (
          <ConfirmDialog
            open={!!actionConfirm}
            onOpenChange={() => setActionConfirm(null)}
            title={isDestructive ? `Destroy ${obj.name}` : 'Confirm Action'}
            description={confirmAction?.confirm || (isDestructive ? `Are you sure you want to destroy "${obj.name}"? This action cannot be undone.` : 'Run this action?')}
            confirmLabel={isDestructive ? 'Destroy' : 'Run'}
            variant={isDestructive ? 'destructive' : undefined}
            onConfirm={() => actionConfirm && actionMutation.mutate(actionConfirm)}
          />
        )
      })()}
    </div>
  )
}

function FieldEditor({
  field,
  formData,
  setFormData,
}: {
  field: InventoryField
  formData: Record<string, unknown>
  setFormData: (d: Record<string, unknown>) => void
}) {
  const value = formData[field.name]

  if (field.readonly) return null

  const update = (val: unknown) => setFormData({ ...formData, [field.name]: val })

  return (
    <div className="space-y-2">
      <Label>{field.label || field.name}</Label>
      {field.type === 'enum' && field.options ? (
        <Select value={String(value || '')} onValueChange={update}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {field.options.map((opt) => (
              <SelectItem key={opt} value={opt}>{opt}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : field.type === 'text' || field.type === 'json' ? (
        <Textarea
          value={typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value || '')}
          onChange={(e) => update(field.type === 'json' ? (() => { try { return JSON.parse(e.target.value) } catch { return e.target.value } })() : e.target.value)}
          rows={4}
          className="font-mono text-xs"
        />
      ) : field.type === 'boolean' ? (
        <Select value={String(!!value)} onValueChange={(v) => update(v === 'true')}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="true">Yes</SelectItem>
            <SelectItem value="false">No</SelectItem>
          </SelectContent>
        </Select>
      ) : (
        <Input
          type={field.type === 'number' ? 'number' : field.type === 'secret' ? 'password' : 'text'}
          value={String(value || '')}
          onChange={(e) => update(field.type === 'number' ? Number(e.target.value) : e.target.value)}
        />
      )}
    </div>
  )
}
