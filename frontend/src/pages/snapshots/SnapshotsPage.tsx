import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ColumnDef } from '@tanstack/react-table'
import { Plus, RefreshCw, MoreHorizontal, Trash, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'

import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { relativeTime } from '@/lib/utils'
import type { Snapshot, InventoryObject } from '@/types'

import { PageHeader } from '@/components/shared/PageHeader'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { DataTable } from '@/components/data/DataTable'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

interface Plan {
  id: string
  vcpu_count: number
  ram: number
  disk: number
  monthly_cost: number
}

export default function SnapshotsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const canCreate = useHasPermission('snapshots.create')
  const canDelete = useHasPermission('snapshots.delete')
  const canRestore = useHasPermission('snapshots.restore')

  // Dialog states
  const [createOpen, setCreateOpen] = useState(false)
  const [deleteSnapshot, setDeleteSnapshot] = useState<Snapshot | null>(null)
  const [restoreSnapshot, setRestoreSnapshot] = useState<Snapshot | null>(null)

  // Create form
  const [createInstanceId, setCreateInstanceId] = useState('')
  const [createDescription, setCreateDescription] = useState('')

  // Restore form
  const [restoreLabel, setRestoreLabel] = useState('')
  const [restoreHostname, setRestoreHostname] = useState('')
  const [restorePlan, setRestorePlan] = useState('')
  const [restoreRegion, setRestoreRegion] = useState('')

  // Data fetching
  const { data: snapshots = [], isLoading } = useQuery({
    queryKey: ['snapshots'],
    queryFn: async () => {
      const { data } = await api.get('/api/snapshots')
      return data.snapshots as Snapshot[]
    },
    refetchInterval: 15000,
  })

  const { data: servers = [] } = useQuery({
    queryKey: ['inventory', 'server'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/server')
      return (data.objects || []) as InventoryObject[]
    },
  })

  const { data: plans = [] } = useQuery({
    queryKey: ['costs', 'plans'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs/plans')
      return (data.plans || []) as Plan[]
    },
    enabled: !!restoreSnapshot,
  })

  // Mutations
  const createMutation = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/api/snapshots', {
        instance_vultr_id: createInstanceId,
        description: createDescription || 'CloudLab snapshot',
      })
      return data
    },
    onSuccess: (data) => {
      toast.success('Snapshot creation started')
      queryClient.invalidateQueries({ queryKey: ['snapshots'] })
      setCreateOpen(false)
      setCreateInstanceId('')
      setCreateDescription('')
      if (data.job_id) navigate(`/jobs/${data.job_id}`)
    },
    onError: () => toast.error('Failed to create snapshot'),
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const { data } = await api.delete(`/api/snapshots/${id}`)
      return data
    },
    onSuccess: (data) => {
      toast.success('Snapshot deletion started')
      queryClient.invalidateQueries({ queryKey: ['snapshots'] })
      setDeleteSnapshot(null)
      if (data.job_id) navigate(`/jobs/${data.job_id}`)
    },
    onError: () => toast.error('Failed to delete snapshot'),
  })

  const restoreMutation = useMutation({
    mutationFn: async (id: number) => {
      const { data } = await api.post(`/api/snapshots/${id}/restore`, {
        label: restoreLabel,
        hostname: restoreHostname,
        plan: restorePlan,
        region: restoreRegion,
      })
      return data
    },
    onSuccess: (data) => {
      toast.success('Snapshot restore started')
      queryClient.invalidateQueries({ queryKey: ['snapshots'] })
      setRestoreSnapshot(null)
      if (data.job_id) navigate(`/jobs/${data.job_id}`)
    },
    onError: () => toast.error('Failed to restore snapshot'),
  })

  const syncMutation = useMutation({
    mutationFn: () => api.post('/api/snapshots/sync'),
    onSuccess: () => {
      toast.success('Snapshot sync started')
      queryClient.invalidateQueries({ queryKey: ['snapshots'] })
    },
    onError: () => toast.error('Failed to sync snapshots'),
  })

  // Open restore dialog with pre-filled values
  const openRestore = (snap: Snapshot) => {
    setRestoreSnapshot(snap)
    setRestoreLabel(`restored-${snap.instance_label || 'snapshot'}`)
    setRestoreHostname('')
    setRestorePlan('')
    setRestoreRegion('')
  }

  const columns = useMemo<ColumnDef<Snapshot>[]>(
    () => [
      {
        accessorKey: 'description',
        header: 'Description',
        cell: ({ row }) => (
          <div>
            <span className="font-medium">{row.original.description || '(no description)'}</span>
            {row.original.vultr_snapshot_id && (
              <p className="text-xs text-muted-foreground font-mono truncate max-w-[200px]">
                {row.original.vultr_snapshot_id}
              </p>
            )}
          </div>
        ),
      },
      {
        accessorKey: 'instance_label',
        header: 'Instance',
        cell: ({ row }) => (
          <span className="text-sm">
            {row.original.instance_label || '-'}
          </span>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: 'size_gb',
        header: 'Size',
        cell: ({ row }) =>
          row.original.size_gb != null ? (
            <Badge variant="secondary">{row.original.size_gb} GB</Badge>
          ) : (
            <span className="text-muted-foreground">-</span>
          ),
      },
      {
        accessorKey: 'created_at',
        header: 'Created',
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {relativeTime(row.original.created_at)}
          </span>
        ),
      },
      {
        id: 'actions',
        cell: ({ row }) => (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                <MoreHorizontal className="h-4 w-4" />
                <span className="sr-only">Actions</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {canRestore && row.original.status === 'complete' && (
                <DropdownMenuItem onClick={() => openRestore(row.original)}>
                  <RotateCcw className="mr-2 h-4 w-4" />
                  Restore
                </DropdownMenuItem>
              )}
              {canDelete && (
                <DropdownMenuItem
                  className="text-destructive"
                  onClick={() => setDeleteSnapshot(row.original)}
                >
                  <Trash className="mr-2 h-4 w-4" />
                  Delete
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    [canDelete, canRestore],
  )

  if (isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="Snapshots" description="Manage Vultr instance snapshots">
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
            Sync
          </Button>
          {canCreate && (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Take Snapshot
            </Button>
          )}
        </div>
      </PageHeader>

      <DataTable
        columns={columns}
        data={snapshots}
        searchKey="description"
        searchPlaceholder="Search snapshots..."
      />

      {/* Take Snapshot Dialog */}
      <Dialog open={createOpen} onOpenChange={(open) => {
        setCreateOpen(open)
        if (!open) { setCreateInstanceId(''); setCreateDescription('') }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Take Snapshot</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>Instance</Label>
              <Select value={createInstanceId} onValueChange={setCreateInstanceId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select an instance" />
                </SelectTrigger>
                <SelectContent>
                  {servers.map((s) => (
                    <SelectItem
                      key={s.id}
                      value={String(s.data.vultr_id || '')}
                    >
                      {s.name} {s.data.vultr_label ? `(${s.data.vultr_label})` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Input
                placeholder="CloudLab snapshot"
                value={createDescription}
                onChange={(e) => setCreateDescription(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={!createInstanceId || createMutation.isPending}
            >
              {createMutation.isPending ? 'Creating...' : 'Take Snapshot'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Restore Snapshot Dialog */}
      <Dialog open={!!restoreSnapshot} onOpenChange={() => {
        setRestoreSnapshot(null)
        setRestoreLabel(''); setRestoreHostname(''); setRestorePlan(''); setRestoreRegion('')
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Restore Snapshot</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              Create a new instance from snapshot: <span className="font-medium text-foreground">{restoreSnapshot?.description}</span>
            </p>
            <div className="space-y-2">
              <Label>Label</Label>
              <Input
                value={restoreLabel}
                onChange={(e) => setRestoreLabel(e.target.value)}
                placeholder="restored-instance"
              />
            </div>
            <div className="space-y-2">
              <Label>Hostname</Label>
              <Input
                value={restoreHostname}
                onChange={(e) => setRestoreHostname(e.target.value)}
                placeholder="restored-instance.example.com"
              />
            </div>
            <div className="space-y-2">
              <Label>Plan</Label>
              <Select value={restorePlan} onValueChange={setRestorePlan}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a plan" />
                </SelectTrigger>
                <SelectContent>
                  {plans.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.id} — {p.vcpu_count} vCPU, {Math.round(p.ram / 1024)}GB RAM, {p.disk}GB SSD — ${p.monthly_cost}/mo
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Region</Label>
              <Select value={restoreRegion} onValueChange={setRestoreRegion}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a region" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="syd">Sydney (syd)</SelectItem>
                  <SelectItem value="mel">Melbourne (mel)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRestoreSnapshot(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => restoreSnapshot && restoreMutation.mutate(restoreSnapshot.id)}
              disabled={
                !restoreLabel || !restoreHostname || !restorePlan || !restoreRegion || restoreMutation.isPending
              }
            >
              {restoreMutation.isPending ? 'Restoring...' : 'Restore'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <ConfirmDialog
        open={!!deleteSnapshot}
        onOpenChange={() => setDeleteSnapshot(null)}
        title="Delete Snapshot"
        description={`Permanently delete snapshot "${deleteSnapshot?.description || deleteSnapshot?.vultr_snapshot_id}"? This will also delete it from Vultr.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteSnapshot && deleteMutation.mutate(deleteSnapshot.id)}
      />
    </div>
  )
}
