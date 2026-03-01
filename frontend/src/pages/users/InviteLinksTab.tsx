import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, MoreHorizontal, Copy, Trash2, XCircle, Users } from 'lucide-react'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { relativeTime } from '@/lib/utils'
import { DataTable } from '@/components/data/DataTable'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
import type { Role } from '@/types'

interface InviteLink {
  id: number
  token: string
  label: string
  expires_at: string | null
  max_uses: number | null
  use_count: number
  is_active: boolean
  status: 'active' | 'expired' | 'revoked' | 'full'
  roles: { id: number; name: string }[]
  created_by: string | null
  created_at: string | null
}

interface Registration {
  id: number
  user_id: number | null
  username: string | null
  display_name: string | null
  email: string | null
  registered_at: string | null
}

const statusVariants: Record<string, 'success' | 'secondary' | 'destructive' | 'outline'> = {
  active: 'success',
  expired: 'secondary',
  revoked: 'destructive',
  full: 'outline',
}

export default function InviteLinksTab() {
  const queryClient = useQueryClient()
  const canManage = useHasPermission('users.invite_links.manage')
  const [createOpen, setCreateOpen] = useState(false)
  const [copyUrl, setCopyUrl] = useState<string | null>(null)
  const [revokeLink, setRevokeLink] = useState<InviteLink | null>(null)
  const [deleteLink, setDeleteLink] = useState<InviteLink | null>(null)
  const [regsLink, setRegsLink] = useState<InviteLink | null>(null)
  const [createForm, setCreateForm] = useState({
    label: '',
    expiry: 'never',
    max_uses: '',
    role_ids: [] as string[],
  })

  const { data: links = [], isLoading } = useQuery({
    queryKey: ['invite-links'],
    queryFn: async () => {
      const { data } = await api.get('/api/invite-links')
      return (data.invite_links || []) as InviteLink[]
    },
  })

  const { data: roles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: async () => {
      const { data } = await api.get('/api/roles')
      return (data.roles || []) as Role[]
    },
  })

  const { data: registrations = [], isLoading: regsLoading } = useQuery({
    queryKey: ['invite-link-registrations', regsLink?.id],
    queryFn: async () => {
      if (!regsLink) return []
      const { data } = await api.get(`/api/invite-links/${regsLink.id}/registrations`)
      return (data.registrations || []) as Registration[]
    },
    enabled: !!regsLink,
  })

  const createMutation = useMutation({
    mutationFn: (body: { label: string; expiry: string; max_uses: number | null; role_ids: number[] }) =>
      api.post('/api/invite-links', body),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['invite-links'] })
      setCreateOpen(false)
      setCreateForm({ label: '', expiry: 'never', max_uses: '', role_ids: [] })
      const token = res.data.token
      if (token) {
        setCopyUrl(`${window.location.origin}/join/${token}`)
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to create invite link'),
  })

  const revokeMutation = useMutation({
    mutationFn: (id: number) => api.post(`/api/invite-links/${id}/revoke`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invite-links'] })
      setRevokeLink(null)
      toast.success('Invite link revoked')
    },
    onError: () => toast.error('Failed to revoke link'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/invite-links/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invite-links'] })
      setDeleteLink(null)
      toast.success('Invite link deleted')
    },
    onError: () => toast.error('Failed to delete link'),
  })

  const handleCreate = () => {
    createMutation.mutate({
      label: createForm.label,
      expiry: createForm.expiry,
      max_uses: createForm.max_uses ? parseInt(createForm.max_uses) : null,
      role_ids: createForm.role_ids.map(Number),
    })
  }

  const toggleRole = (roleId: string) => {
    setCreateForm((prev) => ({
      ...prev,
      role_ids: prev.role_ids.includes(roleId)
        ? prev.role_ids.filter((id) => id !== roleId)
        : [...prev.role_ids, roleId],
    }))
  }

  const columns = useMemo<ColumnDef<InviteLink>[]>(
    () => [
      {
        accessorKey: 'label',
        header: 'Label',
        cell: ({ row }) => <span className="font-medium">{row.original.label}</span>,
      },
      {
        id: 'roles',
        header: 'Roles',
        cell: ({ row }) => (
          <div className="flex gap-1 flex-wrap">
            {row.original.roles.map((r) => (
              <Badge key={r.id} variant="outline" className="text-xs">{r.name}</Badge>
            ))}
          </div>
        ),
      },
      {
        id: 'uses',
        header: 'Uses',
        cell: ({ row }) => (
          <span className="text-sm">
            {row.original.use_count}
            {row.original.max_uses ? ` / ${row.original.max_uses}` : ' / unlimited'}
          </span>
        ),
      },
      {
        accessorKey: 'expires_at',
        header: 'Expires',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">
            {row.original.expires_at ? relativeTime(row.original.expires_at) : 'Never'}
          </span>
        ),
      },
      {
        id: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <Badge variant={statusVariants[row.original.status] || 'secondary'}>
            {row.original.status.charAt(0).toUpperCase() + row.original.status.slice(1)}
          </Badge>
        ),
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
              <DropdownMenuItem onClick={() => {
                const url = `${window.location.origin}/join/${row.original.token}`
                navigator.clipboard.writeText(url)
                toast.success('Link copied to clipboard')
              }}>
                <Copy className="mr-2 h-3 w-3" /> Copy URL
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setRegsLink(row.original)}>
                <Users className="mr-2 h-3 w-3" /> View Registrations
              </DropdownMenuItem>
              {canManage && row.original.status === 'active' && (
                <DropdownMenuItem onClick={() => setRevokeLink(row.original)}>
                  <XCircle className="mr-2 h-3 w-3" /> Revoke
                </DropdownMenuItem>
              )}
              {canManage && (
                <DropdownMenuItem className="text-destructive" onClick={() => setDeleteLink(row.original)}>
                  <Trash2 className="mr-2 h-3 w-3" /> Delete
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    [canManage]
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div />
        {canManage && (
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" /> Create Link
          </Button>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : (
        <DataTable columns={columns} data={links} searchKey="label" searchPlaceholder="Search invite links..." />
      )}

      {/* Create Link Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create Invite Link</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Label</Label>
              <Input
                placeholder="e.g. Spring 2026 Workshop"
                value={createForm.label}
                onChange={(e) => setCreateForm({ ...createForm, label: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Expiry</Label>
              <Select value={createForm.expiry} onValueChange={(v) => setCreateForm({ ...createForm, expiry: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="24h">24 hours</SelectItem>
                  <SelectItem value="7d">7 days</SelectItem>
                  <SelectItem value="30d">30 days</SelectItem>
                  <SelectItem value="never">Never</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Max Uses</Label>
              <Input
                type="number"
                placeholder="Unlimited"
                value={createForm.max_uses}
                onChange={(e) => setCreateForm({ ...createForm, max_uses: e.target.value })}
                min={1}
              />
            </div>
            <div className="space-y-2">
              <Label>Roles</Label>
              <div className="flex flex-wrap gap-2">
                {roles.map((r) => (
                  <Badge
                    key={r.id}
                    variant={createForm.role_ids.includes(String(r.id)) ? 'default' : 'outline'}
                    className="cursor-pointer"
                    onClick={() => toggleRole(String(r.id))}
                  >
                    {r.name}
                  </Badge>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button
              onClick={handleCreate}
              disabled={!createForm.label || createForm.role_ids.length === 0 || createMutation.isPending}
            >
              Create Link
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Copy URL Dialog */}
      <Dialog open={!!copyUrl} onOpenChange={() => setCopyUrl(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Invite Link Created</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Share this URL to allow people to register:</p>
            <div className="flex gap-2">
              <Input value={copyUrl || ''} readOnly className="font-mono text-xs" />
              <Button
                variant="outline"
                size="icon"
                onClick={() => {
                  if (copyUrl) {
                    navigator.clipboard.writeText(copyUrl)
                    toast.success('Copied to clipboard')
                  }
                }}
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setCopyUrl(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Registrations Dialog */}
      <Dialog open={!!regsLink} onOpenChange={() => setRegsLink(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Registrations — {regsLink?.label}</DialogTitle>
          </DialogHeader>
          {regsLoading ? (
            <div className="space-y-2">
              {[1, 2].map((i) => <Skeleton key={i} className="h-8 w-full" />)}
            </div>
          ) : registrations.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">No registrations yet</p>
          ) : (
            <div className="max-h-64 overflow-y-auto space-y-2">
              {registrations.map((r) => (
                <div key={r.id} className="flex items-center justify-between py-2 px-3 rounded-md bg-muted/50">
                  <div>
                    <p className="text-sm font-medium">{r.username}</p>
                    <p className="text-xs text-muted-foreground">{r.email}</p>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {r.registered_at ? relativeTime(r.registered_at) : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setRegsLink(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Revoke Confirm */}
      <ConfirmDialog
        open={!!revokeLink}
        onOpenChange={() => setRevokeLink(null)}
        title="Revoke Invite Link"
        description={`Revoke "${revokeLink?.label}"? No new users will be able to register via this link.`}
        confirmLabel="Revoke"
        variant="destructive"
        onConfirm={() => revokeLink && revokeMutation.mutate(revokeLink.id)}
      />

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteLink}
        onOpenChange={() => setDeleteLink(null)}
        title="Delete Invite Link"
        description={`Permanently delete "${deleteLink?.label}" and all its registration records?`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteLink && deleteMutation.mutate(deleteLink.id)}
      />
    </div>
  )
}
