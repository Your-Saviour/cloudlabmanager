import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, MoreHorizontal, Pencil, Trash2, Info, KeyRound } from 'lucide-react'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import type { Role } from '@/types'
import { PageHeader } from '@/components/shared/PageHeader'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { DataTable } from '@/components/data/DataTable'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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

// ─── Types ─────────────────────────────────────────────────────────────────────

interface CredentialAccessRule {
  id: number
  role_id: number
  role_name: string | null
  credential_type: string
  scope_type: string
  scope_value: string | null
  require_personal_key: boolean
  created_by: number | null
  created_at: string | null
}

interface RuleFormState {
  role_id: string
  credential_type: string
  scope_type: string
  scope_value: string
  require_personal_key: boolean
}

const emptyForm: RuleFormState = {
  role_id: '',
  credential_type: '*',
  scope_type: 'all',
  scope_value: '',
  require_personal_key: false,
}

const CREDENTIAL_TYPES = [
  { value: '*', label: 'All Types' },
  { value: 'ssh_key', label: 'SSH Key' },
  { value: 'password', label: 'Password' },
  { value: 'token', label: 'Token' },
  { value: 'certificate', label: 'Certificate' },
  { value: 'api_key', label: 'API Key' },
]

const SCOPE_TYPES = [
  { value: 'all', label: 'All' },
  { value: 'instance', label: 'Instance' },
  { value: 'service', label: 'Service' },
  { value: 'tag', label: 'Tag' },
]

// ─── Scope options hook ────────────────────────────────────────────────────────

function useScopeOptions(scopeType: string) {
  const { data: servers } = useQuery({
    queryKey: ['inventory', 'server'],
    queryFn: () => api.get('/api/inventory/server').then((r) => r.data.objects),
    enabled: scopeType === 'instance',
  })
  const { data: services } = useQuery({
    queryKey: ['services'],
    queryFn: () => api.get('/api/services').then((r) => r.data),
    enabled: scopeType === 'service',
  })
  const { data: tagsData } = useQuery({
    queryKey: ['inventory-tags'],
    queryFn: () => api.get('/api/inventory/tags').then((r) => r.data.tags),
    enabled: scopeType === 'tag',
  })

  if (scopeType === 'instance') return (servers || []).map((s: any) => s.data?.hostname || s.name).filter(Boolean)
  if (scopeType === 'service') return (services?.services || []).map((s: any) => s.name)
  if (scopeType === 'tag') return (tagsData || []).map((t: any) => t.name)
  return []
}

// ─── Credential type badge ─────────────────────────────────────────────────────

function CredentialTypeBadge({ type }: { type: string }) {
  const label = CREDENTIAL_TYPES.find((t) => t.value === type)?.label || type
  return (
    <Badge variant="outline" className="text-xs border-amber-500/50 text-amber-400">
      {label}
    </Badge>
  )
}

// ─── Page ──────────────────────────────────────────────────────────────────────

export default function CredentialAccessRulesPage() {
  const canManage = useHasPermission('credential_access.manage')
  const queryClient = useQueryClient()

  const { data: rulesData, isLoading } = useQuery({
    queryKey: ['credential-access-rules'],
    queryFn: () => api.get('/api/credential-access/rules').then((r) => r.data),
  })
  const rules: CredentialAccessRule[] = rulesData?.rules || []

  const { data: roles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: async () => {
      const { data } = await api.get('/api/roles')
      return (data.roles || []) as Role[]
    },
  })

  const [createOpen, setCreateOpen] = useState(false)
  const [editRule, setEditRule] = useState<CredentialAccessRule | null>(null)
  const [deleteRule, setDeleteRule] = useState<CredentialAccessRule | null>(null)
  const [form, setForm] = useState<RuleFormState>(emptyForm)

  const scopeOptions = useScopeOptions(form.scope_type)

  const createMutation = useMutation({
    mutationFn: (rule: any) => api.post('/api/credential-access/rules', rule),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credential-access-rules'] })
      setCreateOpen(false)
      setForm(emptyForm)
      toast.success('Rule created')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Create failed'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, ...body }: any) => api.put(`/api/credential-access/rules/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credential-access-rules'] })
      setEditRule(null)
      toast.success('Rule updated')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Update failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/credential-access/rules/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credential-access-rules'] })
      setDeleteRule(null)
      toast.success('Rule deleted')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Delete failed'),
  })

  function openCreate() {
    setForm(emptyForm)
    setCreateOpen(true)
  }

  function openEdit(rule: CredentialAccessRule) {
    setForm({
      role_id: String(rule.role_id),
      credential_type: rule.credential_type,
      scope_type: rule.scope_type,
      scope_value: rule.scope_value || '',
      require_personal_key: rule.require_personal_key,
    })
    setEditRule(rule)
  }

  function buildPayload() {
    if (!form.role_id) {
      toast.error('Role is required')
      return null
    }
    return {
      role_id: Number(form.role_id),
      credential_type: form.credential_type,
      scope_type: form.scope_type,
      scope_value: form.scope_type !== 'all' ? form.scope_value : null,
      require_personal_key: form.require_personal_key,
    }
  }

  function handleCreate() {
    const payload = buildPayload()
    if (!payload) return
    createMutation.mutate(payload)
  }

  function handleUpdate() {
    if (!editRule) return
    const payload = buildPayload()
    if (!payload) return
    updateMutation.mutate({ id: editRule.id, ...payload })
  }

  const roleLabel = (roleId: number) => roles.find((r) => r.id === roleId)?.name || `Role #${roleId}`

  const columns = useMemo<ColumnDef<CredentialAccessRule>[]>(
    () => [
      {
        id: 'role',
        header: 'Role',
        cell: ({ row }) => (
          <span className="font-medium">{row.original.role_name || roleLabel(row.original.role_id)}</span>
        ),
      },
      {
        accessorKey: 'credential_type',
        header: 'Credential Type',
        cell: ({ row }) => <CredentialTypeBadge type={row.original.credential_type} />,
      },
      {
        accessorKey: 'scope_type',
        header: 'Scope',
        cell: ({ row }) => (
          <Badge variant="secondary" className="text-xs">
            {SCOPE_TYPES.find((s) => s.value === row.original.scope_type)?.label || row.original.scope_type}
          </Badge>
        ),
      },
      {
        accessorKey: 'scope_value',
        header: 'Scope Value',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">
            {row.original.scope_value || '—'}
          </span>
        ),
      },
      {
        accessorKey: 'require_personal_key',
        header: 'Personal Key',
        cell: ({ row }) => (
          <Badge variant={row.original.require_personal_key ? 'default' : 'secondary'} className="text-xs">
            {row.original.require_personal_key ? 'Required' : 'No'}
          </Badge>
        ),
      },
      {
        id: 'actions',
        cell: ({ row }) =>
          canManage ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Rule actions">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => openEdit(row.original)}>
                  <Pencil className="mr-2 h-3 w-3" /> Edit
                </DropdownMenuItem>
                <DropdownMenuItem className="text-destructive" onClick={() => setDeleteRule(row.original)}>
                  <Trash2 className="mr-2 h-3 w-3" /> Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null,
      },
    ],
    [canManage, roles],
  )

  const ruleFormFields = (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Role</Label>
        <Select value={form.role_id} onValueChange={(v) => setForm({ ...form, role_id: v })}>
          <SelectTrigger><SelectValue placeholder="Select role..." /></SelectTrigger>
          <SelectContent>
            {roles.map((r) => (
              <SelectItem key={r.id} value={String(r.id)}>{r.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label>Credential Type</Label>
        <Select value={form.credential_type} onValueChange={(v) => setForm({ ...form, credential_type: v })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {CREDENTIAL_TYPES.map((ct) => (
              <SelectItem key={ct.value} value={ct.value}>{ct.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label>Scope Type</Label>
        <Select
          value={form.scope_type}
          onValueChange={(v) => setForm({ ...form, scope_type: v, scope_value: '' })}
        >
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {SCOPE_TYPES.map((st) => (
              <SelectItem key={st.value} value={st.value}>{st.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {form.scope_type !== 'all' && (
        <div className="space-y-2">
          <Label>Scope Value</Label>
          {scopeOptions.length > 0 ? (
            <Select value={form.scope_value} onValueChange={(v) => setForm({ ...form, scope_value: v })}>
              <SelectTrigger><SelectValue placeholder={`Select ${form.scope_type}...`} /></SelectTrigger>
              <SelectContent>
                {scopeOptions.map((opt: string) => (
                  <SelectItem key={opt} value={opt}>{opt}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input
              value={form.scope_value}
              onChange={(e) => setForm({ ...form, scope_value: e.target.value })}
              placeholder={`Enter ${form.scope_type} value...`}
            />
          )}
        </div>
      )}
      {form.credential_type === 'ssh_key' && (
        <div className="flex items-center gap-2">
          <Checkbox
            checked={form.require_personal_key}
            onCheckedChange={(v) => setForm({ ...form, require_personal_key: !!v })}
          />
          <Label className="font-normal">Require personal SSH key</Label>
        </div>
      )}
    </div>
  )

  return (
    <div>
      <PageHeader title="Credential Access Rules" description="Control which roles can access specific credential types and scopes" />

      <div className="flex items-start gap-3 p-3 mt-4 mb-4 rounded-lg border border-blue-500/20 bg-blue-500/5">
        <Info className="h-4 w-4 mt-0.5 text-blue-400 shrink-0" />
        <p className="text-sm text-muted-foreground">
          When no rules exist for a role, users in that role see all credentials they have inventory permission for.
          Adding rules restricts visibility to only matching credentials.
        </p>
      </div>

      <div className="flex justify-end mb-4">
        {canManage && (
          <Button size="sm" onClick={openCreate}>
            <Plus className="mr-2 h-4 w-4" /> Add Rule
          </Button>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : (
        <DataTable columns={columns} data={rules} searchKey="role_name" searchPlaceholder="Search by role..." />
      )}

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create Credential Access Rule</DialogTitle></DialogHeader>
          {ruleFormFields}
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.role_id || createMutation.isPending}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editRule} onOpenChange={() => setEditRule(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Edit Credential Access Rule</DialogTitle></DialogHeader>
          {ruleFormFields}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditRule(null)}>Cancel</Button>
            <Button onClick={handleUpdate} disabled={!form.role_id || updateMutation.isPending}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteRule}
        onOpenChange={() => setDeleteRule(null)}
        title="Delete Rule"
        description={`Permanently delete this credential access rule for role "${deleteRule?.role_name || ''}"?`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => {
          if (deleteRule) deleteMutation.mutate(deleteRule.id)
        }}
      />
    </div>
  )
}
