import { useState, useMemo } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Tag as TagIcon, Search, Trash2, Pencil, Terminal, Monitor, RefreshCw, Square, Eye } from 'lucide-react'
import api from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { useInventoryStore } from '@/stores/inventoryStore'
import { useHasPermission } from '@/lib/permissions'
import { PageHeader } from '@/components/shared/PageHeader'
import { EmptyState } from '@/components/shared/EmptyState'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { BulkActionBar } from '@/components/shared/BulkActionBar'
import { DataTable } from '@/components/data/DataTable'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { toast } from 'sonner'
import { CredentialDisplay } from '@/components/portal/CredentialDisplay'
import { CredentialViewModal } from '@/components/inventory/CredentialViewModal'
import type { ColumnDef, RowSelectionState } from '@tanstack/react-table'
import type { InventoryObject, Tag } from '@/types'

export default function InventoryHubPage() {
  const { typeSlug } = useParams<{ typeSlug: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const types = useInventoryStore((s) => s.types)
  const isTagsView = location.pathname === '/inventory/tags'

  if (isTagsView) return <TagsView />
  if (typeSlug) return <InventoryListView typeSlug={typeSlug} />
  return <InventoryOverview />
}

function InventoryOverview() {
  const navigate = useNavigate()
  const types = useInventoryStore((s) => s.types)

  return (
    <div>
      <PageHeader title="Inventory" description="Manage your infrastructure inventory">
        <Button variant="outline" size="sm" onClick={() => navigate('/inventory/tags')}>
          <TagIcon className="mr-2 h-4 w-4" /> Tags
        </Button>
      </PageHeader>

      {types.length === 0 ? (
        <EmptyState title="No inventory types" description="No inventory types are configured yet." />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {types.map((type) => (
            <Card
              key={type.slug}
              className="cursor-pointer hover:border-primary/50 transition-colors"
              onClick={() => navigate(`/inventory/${type.slug}`)}
            >
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  {type.label}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  {type.fields.length} fields, {type.actions.length} actions
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

function InventoryListView({ typeSlug }: { typeSlug: string }) {
  const navigate = useNavigate()
  const types = useInventoryStore((s) => s.types)
  const typeConfig = types.find((t) => t.slug === typeSlug)
  const canCreate = useHasPermission(`inventory.${typeSlug}.create`)

  const queryClient = useQueryClient()
  const hasSync = !!typeConfig?.sync
  const [destroyTarget, setDestroyTarget] = useState<InventoryObject | null>(null)

  // Bulk selection state
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const selectedCount = Object.keys(rowSelection).length
  const clearSelection = () => setRowSelection({})

  // Bulk delete
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)

  const bulkDeleteMutation = useMutation({
    mutationFn: async (objectIds: number[]) => {
      const { data } = await api.post(`/api/inventory/${typeSlug}/bulk/delete`, { object_ids: objectIds })
      return data
    },
    onSuccess: (data) => {
      clearSelection()
      setBulkDeleteOpen(false)
      toast.success(`Deleted ${data.succeeded.length} items`)
      if (data.skipped?.length > 0) {
        toast.warning(`${data.skipped.length} items skipped (permission denied)`)
      }
      queryClient.invalidateQueries({ queryKey: ['inventory', typeSlug] })
    },
    onError: () => toast.error('Bulk delete failed'),
  })

  // Bulk tag management
  const [bulkTagOpen, setBulkTagOpen] = useState(false)
  const [bulkTagMode, setBulkTagMode] = useState<'add' | 'remove'>('add')
  const [bulkTagIds, setBulkTagIds] = useState<number[]>([])

  const { data: availableTags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/tags')
      return (data.tags || []) as Tag[]
    },
  })

  const bulkTagMutation = useMutation({
    mutationFn: async ({ objectIds, tagIds, mode }: { objectIds: number[], tagIds: number[], mode: 'add' | 'remove' }) => {
      const endpoint = mode === 'add' ? 'tags/add' : 'tags/remove'
      const { data } = await api.post(`/api/inventory/${typeSlug}/bulk/${endpoint}`, {
        object_ids: objectIds,
        tag_ids: tagIds,
      })
      return data
    },
    onSuccess: (data) => {
      clearSelection()
      setBulkTagOpen(false)
      setBulkTagIds([])
      toast.success(`Tags updated on ${data.succeeded.length} items`)
      if (data.skipped?.length > 0) {
        toast.warning(`${data.skipped.length} items skipped`)
      }
      queryClient.invalidateQueries({ queryKey: ['inventory', typeSlug] })
    },
    onError: () => toast.error('Bulk tag update failed'),
  })

  // Bulk action (destroy, stop, etc.)
  const [bulkActionOpen, setBulkActionOpen] = useState<string | null>(null)

  // Super admin credential reveal
  const isSuperAdmin = useAuthStore((s) => s.user?.permissions?.includes('*') ?? false)
  const [credModalOpen, setCredModalOpen] = useState(false)
  const [credModalName, setCredModalName] = useState('')
  const [credModalValue, setCredModalValue] = useState('')

  const bulkActionMutation = useMutation({
    mutationFn: async ({ objectIds, actionName }: { objectIds: number[], actionName: string }) => {
      const { data } = await api.post(`/api/inventory/${typeSlug}/bulk/action/${actionName}`, {
        object_ids: objectIds,
      })
      return data
    },
    onSuccess: (data) => {
      clearSelection()
      setBulkActionOpen(null)
      if (data.job_id) {
        toast.success('Bulk action started')
        navigate(`/jobs/${data.job_id}`)
      }
      if (data.skipped?.length > 0) {
        toast.warning(`${data.skipped.length} items skipped`)
      }
    },
    onError: () => toast.error('Bulk action failed'),
  })

  const destroyMutation = useMutation({
    mutationFn: async (obj: InventoryObject) => {
      const { data } = await api.post(`/api/inventory/${typeSlug}/${obj.id}/actions/destroy`)
      return data
    },
    onSuccess: (data) => {
      setDestroyTarget(null)
      if (data.job_id) {
        toast.success('Destroy started')
        navigate(`/jobs/${data.job_id}`)
      } else {
        toast.success('Destroyed')
        queryClient.invalidateQueries({ queryKey: ['inventory', typeSlug] })
      }
    },
    onError: () => {
      setDestroyTarget(null)
      toast.error('Destroy failed')
    },
  })

  const { data: objects = [], isLoading } = useQuery({
    queryKey: ['inventory', typeSlug],
    queryFn: async () => {
      const { data } = await api.get(`/api/inventory/${typeSlug}`)
      return (data.objects || []) as InventoryObject[]
    },
  })

  const selectedObjects = useMemo(() => {
    return objects.filter((_, i) => rowSelection[String(i)])
  }, [objects, rowSelection])

  const syncSource = typeConfig?.sync && typeof typeConfig.sync === 'object' ? typeConfig.sync.source : typeConfig?.sync
  const needsInstanceRefresh = syncSource === 'vultr_inventory'

  const syncMutation = useMutation({
    mutationFn: async () => {
      if (!hasSync) return

      if (needsInstanceRefresh) {
        // Run the Ansible playbook to refresh from Vultr API
        const { data } = await api.post('/api/instances/refresh')
        const jobId = data.job_id
        if (!jobId) return

        // Poll until the job finishes (it also syncs inventory objects)
        for (let i = 0; i < 120; i++) {
          await new Promise((r) => setTimeout(r, 2000))
          const { data: job } = await api.get(`/api/jobs/${jobId}`)
          if (job.status !== 'running') {
            if (job.status === 'failed') {
              throw new Error('Refresh job failed')
            }
            break
          }
        }
      } else {
        await api.post(`/api/inventory/${typeSlug}/sync`)
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['inventory', typeSlug] })
      toast.success(`${typeConfig?.label || typeSlug} refreshed`)
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ['inventory', typeSlug] })
      toast.error(`Failed to refresh ${typeConfig?.label || typeSlug}`)
    },
  })

  const columns = useMemo<ColumnDef<InventoryObject>[]>(() => {
    const cols: ColumnDef<InventoryObject>[] = [
      {
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => (
          <button
            className="text-primary hover:underline font-medium"
            onClick={() => navigate(`/inventory/${typeSlug}/${row.original.id}`)}
          >
            {row.original.name}
          </button>
        ),
      },
    ]

    if (typeConfig) {
      const LONG_CRED_TYPES = ['ssh_key', 'certificate']

      for (const field of typeConfig.fields.slice(0, 5)) {
        if (field.name === 'name' || field.type === 'json') continue

        // Secret fields: only show for super admin
        if (field.type === 'secret') {
          if (!isSuperAdmin) continue
          cols.push({
            id: field.name,
            header: field.label || field.name,
            cell: ({ row }) => {
              const val = row.original.data[field.name]
              if (val == null || val === '') return <span className="text-muted-foreground text-xs">—</span>
              const credType = row.original.data.credential_type as string | undefined
              const isLong = credType && LONG_CRED_TYPES.includes(credType)

              if (isLong) {
                return (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={(e) => {
                      e.stopPropagation()
                      setCredModalName(row.original.name)
                      setCredModalValue(String(val))
                      setCredModalOpen(true)
                    }}
                  >
                    <Eye className="h-3 w-3 mr-1" /> View
                  </Button>
                )
              }

              return <CredentialDisplay value={String(val)} />
            },
          })
          continue
        }

        cols.push({
          id: field.name,
          header: field.label || field.name,
          accessorFn: (row) => {
            const val = row.data[field.name]
            return val != null ? String(val) : ''
          },
        })
      }
    }

    cols.push({
      id: 'tags',
      header: 'Tags',
      cell: ({ row }) => (
        <div className="flex gap-1 flex-wrap">
          {row.original.tags.map((t) => (
            <Badge key={t.id} variant="outline" className="text-xs" style={{ borderColor: t.color, color: t.color }}>
              {t.name}
            </Badge>
          ))}
        </div>
      ),
    })

    // Add SSH action column if this type has an SSH builtin action
    const hasSSH = typeConfig?.actions.some((a) => a.type === 'builtin' && a.name === 'ssh')
    if (hasSSH) {
      cols.push({
        id: 'ssh',
        header: '',
        cell: ({ row }) => {
          const d = row.original.data
          const isRunning = d.power_status === 'running'
          const hostname = d.hostname as string | undefined
          const ip = d.ip_address as string | undefined
          if (!isRunning || !hostname) return null
          return (
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation()
                navigate(`/ssh/${hostname}/${ip || hostname}`)
              }}
            >
              <Terminal className="mr-1 h-3 w-3" /> SSH
            </Button>
          )
        },
      })
    }

    // Add Console action column if this type has a console builtin action
    const hasConsole = typeConfig?.actions.some((a) => a.type === 'builtin' && a.name === 'console')
    if (hasConsole) {
      cols.push({
        id: 'console',
        header: '',
        cell: ({ row }) => {
          const isRunning = row.original.data.power_status === 'running'
          const kvmUrl = row.original.data.kvm_url as string | undefined
          const isValidUrl = kvmUrl && /^https?:\/\//i.test(kvmUrl)
          if (!isRunning || !isValidUrl) return null
          return (
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation()
                window.open(kvmUrl, '_blank', 'noopener,noreferrer')
              }}
            >
              <Monitor className="mr-1 h-3 w-3" /> Console
            </Button>
          )
        },
      })
    }

    // Add Destroy action column if this type has a destroy action
    const hasDestroy = typeConfig?.actions.some((a) => a.name === 'destroy' && a.scope === 'object')
    if (hasDestroy) {
      cols.push({
        id: 'destroy',
        header: '',
        cell: ({ row }) => {
          const d = row.original.data
          const isRunning = d.power_status === 'running'
          if (!isRunning) return null
          return (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive hover:bg-destructive/10"
              onClick={(e) => {
                e.stopPropagation()
                setDestroyTarget(row.original)
              }}
            >
              <Trash2 className="mr-1 h-3 w-3" /> Destroy
            </Button>
          )
        },
      })
    }

    return cols
  }, [typeSlug, typeConfig, isSuperAdmin])

  // Build bulk actions array
  const bulkActions = useMemo(() => {
    const actions: { label: string; icon?: React.ReactNode; variant?: 'default' | 'destructive' | 'outline'; onClick: () => void }[] = []

    // Tag operations (always available)
    actions.push({
      label: 'Add Tags',
      icon: <TagIcon className="h-3.5 w-3.5" />,
      variant: 'outline' as const,
      onClick: () => { setBulkTagMode('add'); setBulkTagIds([]); setBulkTagOpen(true) },
    })
    actions.push({
      label: 'Remove Tags',
      icon: <TagIcon className="h-3.5 w-3.5" />,
      variant: 'outline' as const,
      onClick: () => { setBulkTagMode('remove'); setBulkTagIds([]); setBulkTagOpen(true) },
    })

    // Destroy action (if type has it)
    const hasDestroyAction = typeConfig?.actions.some(a => a.name === 'destroy' && a.scope === 'object')
    if (hasDestroyAction) {
      actions.push({
        label: 'Destroy',
        icon: <Trash2 className="h-3.5 w-3.5" />,
        variant: 'destructive' as const,
        onClick: () => setBulkActionOpen('destroy'),
      })
    }

    // Stop action (if type has it)
    const hasStopAction = typeConfig?.actions.some(a => a.name === 'stop' && a.scope === 'object')
    if (hasStopAction) {
      actions.push({
        label: 'Stop',
        icon: <Square className="h-3.5 w-3.5" />,
        variant: 'destructive' as const,
        onClick: () => setBulkActionOpen('stop'),
      })
    }

    return actions
  }, [typeConfig])

  return (
    <div>
      <PageHeader title={typeConfig?.label || typeSlug} description={`Manage ${typeConfig?.label || typeSlug} inventory`}>
        <Button variant="outline" size="sm" onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}>
          <RefreshCw className={`mr-2 h-3 w-3 ${syncMutation.isPending ? 'animate-spin' : ''}`} /> Refresh
        </Button>
        {canCreate && (
          <Button size="sm" onClick={() => navigate(`/inventory/${typeSlug}/new`)}>
            <Plus className="mr-2 h-4 w-4" /> Create
          </Button>
        )}
      </PageHeader>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-muted/30 rounded animate-pulse" />
          ))}
        </div>
      ) : objects.length === 0 ? (
        <EmptyState title={`No ${typeConfig?.label || typeSlug}`} description="Create your first item to get started.">
          {canCreate && (
            <Button size="sm" onClick={() => navigate(`/inventory/${typeSlug}/new`)}>
              <Plus className="mr-2 h-4 w-4" /> Create
            </Button>
          )}
        </EmptyState>
      ) : (
        <DataTable
          columns={columns}
          data={objects}
          searchKey="name"
          searchPlaceholder={`Search ${typeConfig?.label || typeSlug}...`}
          enableRowSelection
          rowSelection={rowSelection}
          onRowSelectionChange={setRowSelection}
        />
      )}

      {/* Bulk action bar */}
      <BulkActionBar
        selectedCount={selectedCount}
        onClear={clearSelection}
        itemLabel={typeConfig?.label || typeSlug}
        actions={bulkActions}
      />

      {/* Bulk tag picker dialog */}
      <Dialog open={bulkTagOpen} onOpenChange={(open) => { if (!open) setBulkTagOpen(false) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{bulkTagMode === 'add' ? 'Add Tags' : 'Remove Tags'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 max-h-48 overflow-auto">
            {availableTags.length === 0 ? (
              <p className="text-sm text-muted-foreground py-2">No tags available. Create tags first.</p>
            ) : availableTags.map((tag) => (
              <label key={tag.id} className="flex items-center gap-2 text-sm cursor-pointer">
                <Checkbox
                  checked={bulkTagIds.includes(tag.id)}
                  onCheckedChange={(checked) => {
                    if (checked) setBulkTagIds([...bulkTagIds, tag.id])
                    else setBulkTagIds(bulkTagIds.filter(id => id !== tag.id))
                  }}
                  aria-label={`Select tag ${tag.name}`}
                />
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: tag.color }} />
                <span>{tag.name}</span>
              </label>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkTagOpen(false)}>Cancel</Button>
            <Button
              onClick={() => bulkTagMutation.mutate({
                objectIds: selectedObjects.map(o => o.id),
                tagIds: bulkTagIds,
                mode: bulkTagMode,
              })}
              disabled={bulkTagIds.length === 0}
            >
              {bulkTagMode === 'add' ? 'Add Tags' : 'Remove Tags'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk delete confirm */}
      <ConfirmDialog
        open={bulkDeleteOpen}
        onOpenChange={() => setBulkDeleteOpen(false)}
        title={`Delete ${selectedCount} Items`}
        description={`This will permanently delete ${selectedCount} selected items. This cannot be undone.`}
        confirmLabel="Delete All"
        variant="destructive"
        onConfirm={() => bulkDeleteMutation.mutate(selectedObjects.map(o => o.id))}
      />

      {/* Bulk action confirm (destroy, stop, etc.) */}
      <ConfirmDialog
        open={!!bulkActionOpen}
        onOpenChange={() => setBulkActionOpen(null)}
        title={`${bulkActionOpen ? bulkActionOpen.charAt(0).toUpperCase() + bulkActionOpen.slice(1) : ''} ${selectedCount} Items`}
        description={`Run "${bulkActionOpen}" on ${selectedCount} selected items?`}
        confirmLabel={`${bulkActionOpen ? bulkActionOpen.charAt(0).toUpperCase() + bulkActionOpen.slice(1) : ''} All`}
        variant="destructive"
        onConfirm={() => bulkActionOpen && bulkActionMutation.mutate({
          objectIds: selectedObjects.map(o => o.id),
          actionName: bulkActionOpen,
        })}
      />

      {/* Destroy confirm (single item) */}
      <ConfirmDialog
        open={!!destroyTarget}
        onOpenChange={() => setDestroyTarget(null)}
        title="Destroy Server"
        description={`Are you sure you want to destroy "${destroyTarget?.name}"? This action cannot be undone.`}
        confirmLabel="Destroy"
        variant="destructive"
        onConfirm={() => destroyTarget && destroyMutation.mutate(destroyTarget)}
      />

      {/* Credential view modal (super admin) */}
      <CredentialViewModal
        open={credModalOpen}
        onOpenChange={setCredModalOpen}
        name={credModalName}
        value={credModalValue}
      />
    </div>
  )
}

function TagsView() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [editTag, setEditTag] = useState<Tag | null>(null)
  const [deleteTag, setDeleteTag] = useState<Tag | null>(null)
  const [tagName, setTagName] = useState('')
  const [tagColor, setTagColor] = useState('#6366f1')

  const { data: tags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/tags')
      return (data.tags || []) as Tag[]
    },
  })

  const createMutation = useMutation({
    mutationFn: (body: { name: string; color: string }) => api.post('/api/inventory/tags', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] })
      setCreateOpen(false)
      setTagName('')
      toast.success('Tag created')
    },
    onError: () => toast.error('Failed to create tag'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, ...body }: { id: number; name: string; color: string }) =>
      api.put(`/api/inventory/tags/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] })
      setEditTag(null)
      toast.success('Tag updated')
    },
    onError: () => toast.error('Failed to update tag'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/inventory/tags/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] })
      setDeleteTag(null)
      toast.success('Tag deleted')
    },
    onError: () => toast.error('Failed to delete tag'),
  })

  return (
    <div>
      <PageHeader title="Tags" description="Manage inventory tags">
        <Button size="sm" onClick={() => { setTagName(''); setTagColor('#6366f1'); setCreateOpen(true) }}>
          <Plus className="mr-2 h-4 w-4" /> Create Tag
        </Button>
      </PageHeader>

      {tags.length === 0 ? (
        <EmptyState title="No tags" description="Tags help you organize inventory objects." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {tags.map((tag) => (
            <Card key={tag.id}>
              <CardContent className="pt-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full" style={{ backgroundColor: tag.color }} />
                  <span className="font-medium">{tag.name}</span>
                  {tag.object_count != null && (
                    <span className="text-xs text-muted-foreground">({tag.object_count})</span>
                  )}
                </div>
                <div className="flex gap-1">
                  <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => { setEditTag(tag); setTagName(tag.name); setTagColor(tag.color) }}>
                    <Pencil className="h-3 w-3" />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setDeleteTag(tag)}>
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create Tag</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input value={tagName} onChange={(e) => setTagName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Color</Label>
              <Input type="color" value={tagColor} onChange={(e) => setTagColor(e.target.value)} className="h-10 w-20" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={() => createMutation.mutate({ name: tagName, color: tagColor })} disabled={!tagName.trim()}>Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editTag} onOpenChange={() => setEditTag(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Edit Tag</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input value={tagName} onChange={(e) => setTagName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Color</Label>
              <Input type="color" value={tagColor} onChange={(e) => setTagColor(e.target.value)} className="h-10 w-20" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditTag(null)}>Cancel</Button>
            <Button onClick={() => editTag && updateMutation.mutate({ id: editTag.id, name: tagName, color: tagColor })}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteTag}
        onOpenChange={() => setDeleteTag(null)}
        title="Delete Tag"
        description={`Delete tag "${deleteTag?.name}"? This will remove it from all objects.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteTag && deleteMutation.mutate(deleteTag.id)}
      />
    </div>
  )
}
