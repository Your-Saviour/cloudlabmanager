import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Copy, Trash2, ExternalLink, Link2 } from 'lucide-react'
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
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import type { Role } from '@/types'

interface OnboardingInvite {
  pk: string
  name: string
  expires: string | null
  single_use: boolean
  fixed_data: Record<string, string>
  created_by: string | null
  status: 'active' | 'expired'
  enroll_url: string
}

interface GroupMapping {
  id: number
  group_name: string
  role: { id: number; name: string } | null
  created_by: string | null
  created_at: string | null
}

interface AuthentikGroup {
  pk: string
  name: string
  is_superuser: boolean
}

export function useAuthentikStatus() {
  return useQuery({
    queryKey: ['authentik-status'],
    queryFn: async () => {
      const { data } = await api.get('/api/authentik/status')
      return data as { configured: boolean; reachable?: boolean; flow_exists?: boolean; url?: string; flow_slug?: string; error?: string }
    },
    staleTime: 5 * 60 * 1000,
  })
}

export default function SsoOnboardingTab() {
  const queryClient = useQueryClient()
  const canManage = useHasPermission('users.invite_links.manage')
  const canMapRoles = useHasPermission('users.assign_roles')
  const [createOpen, setCreateOpen] = useState(false)
  const [copyUrl, setCopyUrl] = useState<string | null>(null)
  const [revokeInvite, setRevokeInvite] = useState<OnboardingInvite | null>(null)
  const [deleteMapping, setDeleteMapping] = useState<GroupMapping | null>(null)
  const [createForm, setCreateForm] = useState({ label: '', email: '', name: '', expires_hours: '72' })
  const [mappingForm, setMappingForm] = useState({ group_name: '', role_id: '' })

  const { data: status } = useAuthentikStatus()

  const { data: invites = [], isLoading } = useQuery({
    queryKey: ['authentik-invitations'],
    queryFn: async () => {
      const { data } = await api.get('/api/authentik/invitations')
      return (data.invitations || []) as OnboardingInvite[]
    },
    enabled: !!status?.configured,
  })

  const { data: groups = [] } = useQuery({
    queryKey: ['authentik-groups'],
    queryFn: async () => {
      const { data } = await api.get('/api/authentik/groups')
      return (data.groups || []) as AuthentikGroup[]
    },
    enabled: !!status?.configured && canMapRoles,
  })

  const { data: mappings = [], isLoading: mappingsLoading } = useQuery({
    queryKey: ['authentik-group-mappings'],
    queryFn: async () => {
      const { data } = await api.get('/api/authentik/group-mappings')
      return (data.mappings || []) as GroupMapping[]
    },
  })

  const { data: roles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: async () => {
      const { data } = await api.get('/api/roles')
      return (data.roles || []) as Role[]
    },
  })

  const createMutation = useMutation({
    mutationFn: (body: { label: string; email: string | null; name: string | null; expires_hours: number }) =>
      api.post('/api/authentik/invitations', body),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['authentik-invitations'] })
      setCreateOpen(false)
      setCreateForm({ label: '', email: '', name: '', expires_hours: '72' })
      if (res.data.enroll_url) setCopyUrl(res.data.enroll_url)
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to create invitation'),
  })

  const revokeMutation = useMutation({
    mutationFn: (pk: string) => api.delete(`/api/authentik/invitations/${pk}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['authentik-invitations'] })
      setRevokeInvite(null)
      toast.success('Invitation revoked')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to revoke invitation'),
  })

  const createMappingMutation = useMutation({
    mutationFn: (body: { group_name: string; role_id: number }) =>
      api.post('/api/authentik/group-mappings', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['authentik-group-mappings'] })
      setMappingForm({ group_name: '', role_id: '' })
      toast.success('Group mapping added')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to add mapping'),
  })

  const deleteMappingMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/authentik/group-mappings/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['authentik-group-mappings'] })
      setDeleteMapping(null)
      toast.success('Group mapping removed')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to remove mapping'),
  })

  const columns = useMemo<ColumnDef<OnboardingInvite>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Invitation',
        cell: ({ row }) => <span className="font-medium font-mono text-xs">{row.original.name}</span>,
      },
      {
        id: 'for',
        header: 'For',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">
            {row.original.fixed_data.name || row.original.fixed_data.email || '—'}
          </span>
        ),
      },
      {
        accessorKey: 'expires',
        header: 'Expires',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">
            {row.original.expires ? relativeTime(row.original.expires) : 'Never'}
          </span>
        ),
      },
      {
        id: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <Badge variant={row.original.status === 'active' ? 'success' : 'secondary'}>
            {row.original.status === 'active' ? 'Active' : 'Expired'}
          </Badge>
        ),
      },
      {
        id: 'actions',
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              title="Copy enrollment link"
              onClick={() => {
                navigator.clipboard.writeText(row.original.enroll_url)
                toast.success('Enrollment link copied')
              }}
            >
              <Copy className="h-4 w-4" />
            </Button>
            {canManage && (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-destructive"
                title="Revoke invitation"
                onClick={() => setRevokeInvite(row.original)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        ),
      },
    ],
    [canManage]
  )

  if (status && !status.configured) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        Authentik integration is not configured on this CLM instance.
      </p>
    )
  }

  return (
    <div className="space-y-8">
      {/* Onboarding invitations */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-medium">Onboarding Invitations</h3>
            <p className="text-xs text-muted-foreground">
              Single-use enrollment links. The user sets their own username and password in{' '}
              {status?.url ? (
                <a href={status.url} target="_blank" rel="noreferrer" className="underline inline-flex items-center gap-0.5">
                  Authentik <ExternalLink className="h-3 w-3" />
                </a>
              ) : (
                'Authentik'
              )}
              , then signs in to CLM via SSO.
            </p>
          </div>
          {canManage && (
            <Button size="sm" onClick={() => setCreateOpen(true)} disabled={status?.flow_exists === false}>
              <Plus className="mr-2 h-4 w-4" /> New Invitation
            </Button>
          )}
        </div>

        {status?.flow_exists === false && (
          <p className="text-xs text-destructive mb-3">
            Enrollment flow "{status.flow_slug}" was not found in Authentik — deploy the authentik service onboarding stage first.
          </p>
        )}

        {isLoading ? (
          <div className="space-y-2">
            {[1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
          </div>
        ) : invites.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center border rounded-md">
            No open invitations. Used invitations disappear automatically.
          </p>
        ) : (
          <DataTable columns={columns} data={invites} searchKey="name" searchPlaceholder="Search invitations..." />
        )}
      </div>

      {/* Group -> role mappings */}
      <div>
        <div className="mb-4">
          <h3 className="text-sm font-medium flex items-center gap-1.5">
            <Link2 className="h-4 w-4" /> Group → Role Mappings
          </h3>
          <p className="text-xs text-muted-foreground">
            Authentik group membership grants the mapped CLM role on every SSO login (and removes it when
            membership is lost). Roles without a mapping stay manually managed.
          </p>
        </div>

        {mappingsLoading ? (
          <Skeleton className="h-12 w-full" />
        ) : (
          <div className="border rounded-md divide-y">
            {mappings.length === 0 && (
              <p className="text-sm text-muted-foreground py-4 text-center">No mappings defined</p>
            )}
            {mappings.map((m) => (
              <div key={m.id} className="flex items-center justify-between px-3 py-2">
                <div className="flex items-center gap-2 text-sm">
                  <Badge variant="outline" className="font-mono text-xs">{m.group_name}</Badge>
                  <span className="text-muted-foreground">→</span>
                  <Badge variant="default" className="text-xs">{m.role?.name || 'deleted role'}</Badge>
                </div>
                {canMapRoles && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-destructive"
                    onClick={() => setDeleteMapping(m)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}

        {canMapRoles && (
          <div className="flex items-end gap-2 mt-3">
            <div className="space-y-1 flex-1">
              <Label className="text-xs">Authentik group</Label>
              <Select value={mappingForm.group_name} onValueChange={(v) => setMappingForm({ ...mappingForm, group_name: v })}>
                <SelectTrigger><SelectValue placeholder="Select group..." /></SelectTrigger>
                <SelectContent>
                  {groups.map((g) => (
                    <SelectItem key={g.pk} value={g.name}>{g.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1 flex-1">
              <Label className="text-xs">CLM role</Label>
              <Select value={mappingForm.role_id} onValueChange={(v) => setMappingForm({ ...mappingForm, role_id: v })}>
                <SelectTrigger><SelectValue placeholder="Select role..." /></SelectTrigger>
                <SelectContent>
                  {roles.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)}>{r.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              size="sm"
              onClick={() => createMappingMutation.mutate({ group_name: mappingForm.group_name, role_id: Number(mappingForm.role_id) })}
              disabled={!mappingForm.group_name || !mappingForm.role_id || createMappingMutation.isPending}
            >
              <Plus className="mr-2 h-4 w-4" /> Add Mapping
            </Button>
          </div>
        )}
      </div>

      {/* Create Invitation Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>New Onboarding Invitation</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Label</Label>
              <Input
                placeholder="e.g. jane-doe"
                value={createForm.label}
                onChange={(e) => setCreateForm({ ...createForm, label: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">Used to identify the invitation in the list.</p>
            </div>
            <div className="space-y-2">
              <Label>Email (optional, pre-filled in the enrollment form)</Label>
              <Input
                type="email"
                value={createForm.email}
                onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Full name (optional, pre-filled)</Label>
              <Input
                value={createForm.name}
                onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Expires</Label>
              <Select value={createForm.expires_hours} onValueChange={(v) => setCreateForm({ ...createForm, expires_hours: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="24">24 hours</SelectItem>
                  <SelectItem value="72">3 days</SelectItem>
                  <SelectItem value="168">7 days</SelectItem>
                  <SelectItem value="720">30 days</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button
              onClick={() => createMutation.mutate({
                label: createForm.label,
                email: createForm.email || null,
                name: createForm.name || null,
                expires_hours: Number(createForm.expires_hours),
              })}
              disabled={!createForm.label || createMutation.isPending}
            >
              Create Invitation
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Copy URL Dialog */}
      <Dialog open={!!copyUrl} onOpenChange={() => setCopyUrl(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Invitation Created</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Share this single-use enrollment link. It stops working after the account is created.
            </p>
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

      {/* Revoke Confirm */}
      <ConfirmDialog
        open={!!revokeInvite}
        onOpenChange={() => setRevokeInvite(null)}
        title="Revoke Invitation"
        description={`Revoke invitation "${revokeInvite?.name}"? The enrollment link will stop working immediately.`}
        confirmLabel="Revoke"
        variant="destructive"
        onConfirm={() => revokeInvite && revokeMutation.mutate(revokeInvite.pk)}
      />

      {/* Delete Mapping Confirm */}
      <ConfirmDialog
        open={!!deleteMapping}
        onOpenChange={() => setDeleteMapping(null)}
        title="Remove Group Mapping"
        description={`Remove mapping "${deleteMapping?.group_name}" → "${deleteMapping?.role?.name}"? The role stops being group-managed; users who currently have it keep it.`}
        confirmLabel="Remove"
        variant="destructive"
        onConfirm={() => deleteMapping && deleteMappingMutation.mutate(deleteMapping.id)}
      />
    </div>
  )
}
