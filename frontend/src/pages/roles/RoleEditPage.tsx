import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Save } from 'lucide-react'
import api from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'

interface PermissionItem {
  id: number
  codename: string
  label: string
  description?: string
}

export default function RoleEditPage() {
  const { roleId } = useParams<{ roleId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selectedPerms, setSelectedPerms] = useState<Set<number>>(new Set())

  const { data: role, isLoading: roleLoading } = useQuery({
    queryKey: ['role', roleId],
    queryFn: async () => {
      const { data } = await api.get(`/api/roles/${roleId}`)
      return data
    },
    enabled: !!roleId,
  })

  const { data: allPermissions, isLoading: permsLoading } = useQuery({
    queryKey: ['permissions'],
    queryFn: async () => {
      const { data } = await api.get('/api/roles/permissions')
      return data.permissions as Record<string, PermissionItem[]>
    },
  })

  useEffect(() => {
    if (role) {
      setName(role.name)
      setDescription(role.description || '')
      setSelectedPerms(new Set(role.permissions.map((p: any) => p.id)))
    }
  }, [role])

  const updateMutation = useMutation({
    mutationFn: () =>
      api.put(`/api/roles/${roleId}`, {
        name,
        description,
        permission_ids: Array.from(selectedPerms),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['role', roleId] })
      queryClient.invalidateQueries({ queryKey: ['roles'] })
      toast.success('Role updated')
    },
    onError: () => toast.error('Update failed'),
  })

  const togglePerm = (id: number) => {
    const next = new Set(selectedPerms)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelectedPerms(next)
  }

  const toggleCategory = (perms: PermissionItem[]) => {
    const allSelected = perms.every((p) => selectedPerms.has(p.id))
    const next = new Set(selectedPerms)
    perms.forEach((p) => {
      if (allSelected) next.delete(p.id)
      else next.add(p.id)
    })
    setSelectedPerms(next)
  }

  if (roleLoading || permsLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="icon" onClick={() => navigate('/roles')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">Edit Role</h1>
          <p className="text-sm text-muted-foreground">{role?.name}</p>
        </div>
        <Button size="sm" onClick={() => updateMutation.mutate()} disabled={updateMutation.isPending}>
          <Save className="mr-2 h-3 w-3" /> Save
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        <Card>
          <CardHeader><CardTitle className="text-sm">Details</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-sm">Permissions</CardTitle></CardHeader>
          <CardContent>
            {allPermissions && Object.entries(allPermissions).map(([category, perms]) => (
              <div key={category} className="mb-6 last:mb-0">
                <div className="flex items-center gap-2 mb-3">
                  <Checkbox
                    checked={perms.every((p) => selectedPerms.has(p.id))}
                    onCheckedChange={() => toggleCategory(perms)}
                  />
                  <span className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">{category}</span>
                </div>
                <div className="grid gap-2 sm:grid-cols-2 pl-6">
                  {perms.map((perm) => (
                    <label key={perm.id} className="flex items-center gap-2 cursor-pointer">
                      <Checkbox
                        checked={selectedPerms.has(perm.id)}
                        onCheckedChange={() => togglePerm(perm.id)}
                      />
                      <span className="text-sm">{perm.label || perm.codename}</span>
                    </label>
                  ))}
                </div>
                <Separator className="mt-4" />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
