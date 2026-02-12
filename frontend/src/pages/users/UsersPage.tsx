import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, MoreHorizontal, Mail, Pencil, UserCheck, UserX, Copy } from 'lucide-react'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { useAuthStore } from '@/stores/authStore'
import { relativeTime } from '@/lib/utils'
import { PageHeader } from '@/components/shared/PageHeader'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { DataTable } from '@/components/data/DataTable'
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
import type { User, Role } from '@/types'

export default function UsersPage() {
  const queryClient = useQueryClient()
  const currentUser = useAuthStore((s) => s.user)
  const canCreate = useHasPermission('users.create')
  const canEdit = useHasPermission('users.edit')
  const canDelete = useHasPermission('users.delete')
  const [inviteOpen, setInviteOpen] = useState(false)
  const [deleteUser, setDeleteUser] = useState<User | null>(null)
  const [editUser, setEditUser] = useState<User | null>(null)
  const [toggleUser, setToggleUser] = useState<User | null>(null)
  const [inviteUrl, setInviteUrl] = useState<string | null>(null)

  const [inviteForm, setInviteForm] = useState({ username: '', email: '', display_name: '', role_id: '' })
  const [editForm, setEditForm] = useState({ display_name: '', email: '', role_id: '' })

  const { data: users = [], isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: async () => {
      const { data } = await api.get('/api/users')
      return (data.users || []) as User[]
    },
  })

  const { data: roles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: async () => {
      const { data } = await api.get('/api/roles')
      return (data.roles || []) as Role[]
    },
  })

  const inviteMutation = useMutation({
    mutationFn: (body: typeof inviteForm) =>
      api.post('/api/users/invite', { ...body, role_id: Number(body.role_id) }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setInviteOpen(false)
      setInviteForm({ username: '', email: '', display_name: '', role_id: '' })
      // Show invite URL
      const token = res.data.token || res.data.invite_token
      if (token) {
        setInviteUrl(`${window.location.origin}/accept-invite/${token}`)
      } else {
        toast.success('Invite sent')
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Invite failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/users/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setDeleteUser(null)
      toast.success('User deleted')
    },
    onError: () => toast.error('Delete failed'),
  })

  const resendMutation = useMutation({
    mutationFn: (id: number) => api.post(`/api/users/${id}/resend-invite`),
    onSuccess: () => toast.success('Invite resent'),
    onError: () => toast.error('Resend failed'),
  })

  const editMutation = useMutation({
    mutationFn: async ({ id, form }: { id: number; form: typeof editForm }) => {
      await api.put(`/api/users/${id}`, { display_name: form.display_name, email: form.email })
      if (form.role_id) {
        await api.put(`/api/users/${id}/roles`, { role_ids: [Number(form.role_id)] })
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setEditUser(null)
      toast.success('User updated')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Update failed'),
  })

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      api.put(`/api/users/${id}`, { is_active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setToggleUser(null)
      toast.success('User updated')
    },
    onError: () => toast.error('Update failed'),
  })

  const openEditDialog = (user: User) => {
    setEditForm({
      display_name: user.display_name,
      email: user.email,
      role_id: user.roles[0]?.id ? String(user.roles[0].id) : '',
    })
    setEditUser(user)
  }

  const columns = useMemo<ColumnDef<User>[]>(
    () => [
      {
        accessorKey: 'username',
        header: 'Username',
        cell: ({ row }) => <span className="font-medium">{row.original.username}</span>,
      },
      {
        accessorKey: 'display_name',
        header: 'Display Name',
      },
      {
        accessorKey: 'email',
        header: 'Email',
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.email}</span>,
      },
      {
        id: 'roles',
        header: 'Roles',
        cell: ({ row }) => (
          <div className="flex gap-1">
            {row.original.roles.map((r) => (
              <Badge key={r.id} variant="outline" className="text-xs">{r.name}</Badge>
            ))}
          </div>
        ),
      },
      {
        accessorKey: 'is_active',
        header: 'Status',
        cell: ({ row }) => (
          <Badge variant={row.original.is_active ? 'success' : 'secondary'}>
            {row.original.is_active ? 'Active' : 'Inactive'}
          </Badge>
        ),
      },
      {
        accessorKey: 'last_login_at',
        header: 'Last Login',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">
            {row.original.last_login_at ? relativeTime(row.original.last_login_at) : 'never'}
          </span>
        ),
      },
      {
        id: 'actions',
        cell: ({ row }) => {
          const isSelf = currentUser?.id === row.original.id
          return (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {canEdit && (
                  <DropdownMenuItem onClick={() => openEditDialog(row.original)}>
                    <Pencil className="mr-2 h-3 w-3" /> Edit
                  </DropdownMenuItem>
                )}
                {canEdit && !isSelf && (
                  <DropdownMenuItem
                    onClick={() => setToggleUser(row.original)}
                  >
                    {row.original.is_active ? (
                      <><UserX className="mr-2 h-3 w-3" /> Deactivate</>
                    ) : (
                      <><UserCheck className="mr-2 h-3 w-3" /> Activate</>
                    )}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => resendMutation.mutate(row.original.id)}>
                  <Mail className="mr-2 h-3 w-3" /> Resend Invite
                </DropdownMenuItem>
                {canDelete && (
                  <DropdownMenuItem className="text-destructive" onClick={() => setDeleteUser(row.original)}>
                    Delete
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )
        },
      },
    ],
    [canDelete, canEdit, currentUser]
  )

  return (
    <div>
      <PageHeader title="Users" description="Manage user accounts and invitations">
        {canCreate && (
          <Button size="sm" onClick={() => setInviteOpen(true)}>
            <Plus className="mr-2 h-4 w-4" /> Invite User
          </Button>
        )}
      </PageHeader>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : (
        <DataTable columns={columns} data={users} searchKey="username" searchPlaceholder="Search users..." />
      )}

      {/* Invite Dialog */}
      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Invite User</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Username</Label>
              <Input value={inviteForm.username} onChange={(e) => setInviteForm({ ...inviteForm, username: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input type="email" value={inviteForm.email} onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>Display Name</Label>
              <Input value={inviteForm.display_name} onChange={(e) => setInviteForm({ ...inviteForm, display_name: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>Role</Label>
              <Select value={inviteForm.role_id} onValueChange={(v) => setInviteForm({ ...inviteForm, role_id: v })}>
                <SelectTrigger><SelectValue placeholder="Select role..." /></SelectTrigger>
                <SelectContent>
                  {roles.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)}>{r.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setInviteOpen(false)}>Cancel</Button>
            <Button onClick={() => inviteMutation.mutate(inviteForm)} disabled={!inviteForm.username || !inviteForm.email || !inviteForm.role_id}>
              Send Invite
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Invite URL Dialog */}
      <Dialog open={!!inviteUrl} onOpenChange={() => setInviteUrl(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Invite Created</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Share this URL with the user to complete registration:</p>
            <div className="flex gap-2">
              <Input value={inviteUrl || ''} readOnly className="font-mono text-xs" />
              <Button
                variant="outline"
                size="icon"
                onClick={() => {
                  if (inviteUrl) {
                    navigator.clipboard.writeText(inviteUrl)
                    toast.success('Copied to clipboard')
                  }
                }}
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setInviteUrl(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit User Dialog */}
      <Dialog open={!!editUser} onOpenChange={() => setEditUser(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Edit User - {editUser?.username}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Display Name</Label>
              <Input value={editForm.display_name} onChange={(e) => setEditForm({ ...editForm, display_name: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input type="email" value={editForm.email} onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>Role</Label>
              <Select value={editForm.role_id} onValueChange={(v) => setEditForm({ ...editForm, role_id: v })}>
                <SelectTrigger><SelectValue placeholder="Select role..." /></SelectTrigger>
                <SelectContent>
                  {roles.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)}>{r.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditUser(null)}>Cancel</Button>
            <Button
              onClick={() => editUser && editMutation.mutate({ id: editUser.id, form: editForm })}
              disabled={editMutation.isPending}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Activate/Deactivate Confirm */}
      <ConfirmDialog
        open={!!toggleUser}
        onOpenChange={() => setToggleUser(null)}
        title={toggleUser?.is_active ? 'Deactivate User' : 'Activate User'}
        description={`${toggleUser?.is_active ? 'Deactivate' : 'Activate'} user "${toggleUser?.username}"?`}
        confirmLabel={toggleUser?.is_active ? 'Deactivate' : 'Activate'}
        variant={toggleUser?.is_active ? 'destructive' : 'default'}
        onConfirm={() => toggleUser && toggleActiveMutation.mutate({ id: toggleUser.id, is_active: !toggleUser.is_active })}
      />

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteUser}
        onOpenChange={() => setDeleteUser(null)}
        title="Delete User"
        description={`Permanently delete user "${deleteUser?.username}"?`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteUser && deleteMutation.mutate(deleteUser.id)}
      />
    </div>
  )
}
