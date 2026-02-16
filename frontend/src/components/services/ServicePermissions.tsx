import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Info, Shield } from 'lucide-react'
import api from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { toast } from 'sonner'
import type { ServiceACLEntry, ServicePermission, Role } from '@/types'

const ALL_PERMISSIONS: { value: ServicePermission; label: string; color: string }[] = [
  { value: 'view', label: 'View', color: 'bg-blue-500/15 text-blue-400 border-blue-500/30' },
  { value: 'deploy', label: 'Deploy', color: 'bg-green-500/15 text-green-400 border-green-500/30' },
  { value: 'stop', label: 'Stop', color: 'bg-red-500/15 text-red-400 border-red-500/30' },
  { value: 'config', label: 'Config', color: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
]

interface Props {
  serviceName: string
}

export default function ServicePermissions({ serviceName }: Props) {
  const queryClient = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [form, setForm] = useState<{ role_id: string; permissions: ServicePermission[] }>({
    role_id: '',
    permissions: [],
  })

  const { data: acl = [], isLoading } = useQuery({
    queryKey: ['service', serviceName, 'acl'],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${serviceName}/acl`)
      return (data.acl || []) as ServiceACLEntry[]
    },
    enabled: !!serviceName,
  })

  const { data: roles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: async () => {
      const { data } = await api.get('/api/roles')
      return (data.roles || []) as Role[]
    },
  })

  // Group ACL entries by role
  const groupedByRole = useMemo(() => {
    const map = new Map<number, { role_id: number; role_name: string; permissions: ServiceACLEntry[] }>()
    for (const entry of acl) {
      if (!map.has(entry.role_id)) {
        map.set(entry.role_id, { role_id: entry.role_id, role_name: entry.role_name || `Role #${entry.role_id}`, permissions: [] })
      }
      map.get(entry.role_id)!.permissions.push(entry)
    }
    return Array.from(map.values())
  }, [acl])

  // Roles not yet assigned to this service
  const availableRoles = useMemo(() => {
    const assignedRoleIds = new Set(groupedByRole.map((g) => g.role_id))
    return roles.filter((r) => !assignedRoleIds.has(r.id))
  }, [roles, groupedByRole])

  const addMutation = useMutation({
    mutationFn: (body: { role_id: number; permissions: string[] }) =>
      api.post(`/api/services/${serviceName}/acl`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service', serviceName, 'acl'] })
      toast.success('Permissions added')
      setAddOpen(false)
      setForm({ role_id: '', permissions: [] })
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to add permissions'),
  })

  const deleteRoleMutation = useMutation({
    mutationFn: (aclIds: number[]) =>
      Promise.all(aclIds.map((id) => api.delete(`/api/services/${serviceName}/acl/${id}`))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service', serviceName, 'acl'] })
      toast.success('Role permissions removed')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to remove permissions'),
  })

  const togglePermission = (perm: ServicePermission) => {
    setForm((prev) => ({
      ...prev,
      permissions: prev.permissions.includes(perm)
        ? prev.permissions.filter((p) => p !== perm)
        : [...prev.permissions, perm],
    }))
  }

  const handleAdd = () => {
    if (!form.role_id || form.permissions.length === 0) return
    addMutation.mutate({ role_id: Number(form.role_id), permissions: form.permissions })
  }

  const permBadgeColor = (perm: string) => {
    return ALL_PERMISSIONS.find((p) => p.value === perm)?.color || ''
  }

  if (isLoading) {
    return <div className="space-y-2">{[1, 2, 3].map((i) => <div key={i} className="h-10 w-full rounded-md bg-muted/30 animate-pulse" />)}</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-lg border border-blue-500/20 bg-blue-500/5 p-3">
        <Info className="h-4 w-4 text-blue-400 mt-0.5 shrink-0" />
        <p className="text-xs text-muted-foreground">
          When service permissions are configured, only users with matching role access can interact with this service.
          Users with no matching role will be denied access even if they have global permissions.
        </p>
      </div>

      {groupedByRole.length === 0 ? (
        <Card>
          <CardContent className="pt-6">
            <div className="text-center py-6 space-y-2">
              <Shield className="h-8 w-8 text-muted-foreground/40 mx-auto" />
              <p className="text-sm text-muted-foreground">No service-specific permissions configured.</p>
              <p className="text-xs text-muted-foreground/70">Access is controlled by global RBAC permissions.</p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="pt-4">
            <div className="space-y-1">
              {groupedByRole.map((group) => (
                <div key={group.role_id} className="flex items-center justify-between px-3 py-2.5 rounded-md bg-muted/30">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="text-sm font-medium shrink-0">{group.role_name}</span>
                    <div className="flex flex-wrap gap-1.5">
                      {ALL_PERMISSIONS.map((p) => {
                        const hasIt = group.permissions.some((e) => e.permission === p.value)
                        if (!hasIt) return null
                        return (
                          <Badge key={p.value} variant="outline" className={`text-[10px] ${p.color}`}>
                            {p.label}
                          </Badge>
                        )
                      })}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-muted-foreground hover:text-destructive shrink-0"
                    onClick={() => deleteRoleMutation.mutate(group.permissions.map((e) => e.id))}
                    disabled={deleteRoleMutation.isPending}
                    aria-label={`Remove all permissions for ${group.role_name}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Button size="sm" variant="outline" onClick={() => setAddOpen(true)} disabled={availableRoles.length === 0}>
        <Plus className="mr-2 h-3 w-3" /> Add Role Access
      </Button>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Role Access</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>Role</Label>
              <Select value={form.role_id} onValueChange={(v) => setForm({ ...form, role_id: v })}>
                <SelectTrigger>
                  <SelectValue placeholder="Select role..." />
                </SelectTrigger>
                <SelectContent>
                  {availableRoles.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)}>{r.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Permissions</Label>
              <div className="grid grid-cols-2 gap-3">
                {ALL_PERMISSIONS.map((p) => (
                  <label key={p.value} className="flex items-center gap-2 cursor-pointer">
                    <Checkbox
                      checked={form.permissions.includes(p.value)}
                      onCheckedChange={() => togglePermission(p.value)}
                    />
                    <Badge variant="outline" className={`text-xs ${p.color}`}>{p.label}</Badge>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button onClick={handleAdd} disabled={!form.role_id || form.permissions.length === 0 || addMutation.isPending}>
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
