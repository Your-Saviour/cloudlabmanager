import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, MoreHorizontal, Bell, Hash, Mail, Pencil, Send } from 'lucide-react'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import {
  useNotificationRules,
  useCreateRule,
  useUpdateRule,
  useDeleteRule,
  useEventTypes,
  useNotificationChannels,
  useCreateChannel,
  useUpdateChannel,
  useDeleteChannel,
  useTestChannel,
} from '@/hooks/useNotificationRules'
import type { NotificationRule, NotificationChannel } from '@/hooks/useNotificationRules'
import type { Role } from '@/types'
import { PageHeader } from '@/components/shared/PageHeader'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { DataTable } from '@/components/data/DataTable'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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

const CHANNEL_LABELS: Record<string, string> = {
  in_app: 'In-App',
  email: 'Email',
  slack: 'Slack',
}

function channelIcon(channel: string) {
  switch (channel) {
    case 'slack': return <Hash className="h-3 w-3" />
    case 'email': return <Mail className="h-3 w-3" />
    default: return <Bell className="h-3 w-3" />
  }
}

// ─── Rules Tab ───────────────────────────────────────────────────────────────

interface RuleFormState {
  name: string
  event_type: string
  channel: string
  slack_channel_id: string
  role_id: string
  filters: string
  enabled: boolean
}

const emptyRuleForm: RuleFormState = {
  name: '',
  event_type: '',
  channel: 'in_app',
  slack_channel_id: '',
  role_id: '',
  filters: '',
  enabled: true,
}

function RulesTab() {
  const canManage = useHasPermission('notifications.rules.manage')
  const { data: rulesData, isLoading } = useNotificationRules()
  const { data: eventTypesData } = useEventTypes()
  const { data: channelsData } = useNotificationChannels()
  const { data: roles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: async () => {
      const { data } = await api.get('/api/roles')
      return (data.roles || []) as Role[]
    },
  })

  const rules = rulesData?.rules || []
  const eventTypes = eventTypesData?.event_types || []
  const slackChannels = channelsData?.channels || []

  const [createOpen, setCreateOpen] = useState(false)
  const [editRule, setEditRule] = useState<NotificationRule | null>(null)
  const [deleteRule, setDeleteRule] = useState<NotificationRule | null>(null)
  const [form, setForm] = useState<RuleFormState>(emptyRuleForm)

  const createMutation = useCreateRule()
  const updateMutation = useUpdateRule()
  const deleteMutation = useDeleteRule()
  const toggleMutation = useUpdateRule()

  function openCreate() {
    setForm(emptyRuleForm)
    setCreateOpen(true)
  }

  function openEdit(rule: NotificationRule) {
    setForm({
      name: rule.name,
      event_type: rule.event_type,
      channel: rule.channel,
      slack_channel_id: rule.slack_channel_id ? String(rule.slack_channel_id) : '',
      role_id: rule.role_id ? String(rule.role_id) : '',
      filters: rule.filters ? JSON.stringify(rule.filters, null, 2) : '',
      enabled: rule.enabled,
    })
    setEditRule(rule)
  }

  function buildPayload() {
    let filters: Record<string, unknown> | null = null
    if (form.filters.trim()) {
      try {
        filters = JSON.parse(form.filters)
      } catch {
        toast.error('Invalid JSON in filters')
        return null
      }
    }
    return {
      name: form.name,
      event_type: form.event_type,
      channel: form.channel,
      slack_channel_id: form.channel === 'slack' && form.slack_channel_id ? Number(form.slack_channel_id) : null,
      role_id: form.role_id ? Number(form.role_id) : null,
      filters,
      enabled: form.enabled,
    }
  }

  function handleCreate() {
    const payload = buildPayload()
    if (!payload) return
    createMutation.mutate(payload, {
      onSuccess: () => {
        setCreateOpen(false)
        setForm(emptyRuleForm)
        toast.success('Rule created')
      },
      onError: (err: any) => toast.error(err.response?.data?.detail || 'Create failed'),
    })
  }

  function handleUpdate() {
    if (!editRule) return
    const payload = buildPayload()
    if (!payload) return
    updateMutation.mutate({ id: editRule.id, ...payload }, {
      onSuccess: () => {
        setEditRule(null)
        toast.success('Rule updated')
      },
      onError: (err: any) => toast.error(err.response?.data?.detail || 'Update failed'),
    })
  }

  function handleToggle(rule: NotificationRule) {
    toggleMutation.mutate({ id: rule.id, enabled: !rule.enabled }, {
      onSuccess: () => toast.success(`Rule ${rule.enabled ? 'disabled' : 'enabled'}`),
      onError: () => toast.error('Toggle failed'),
    })
  }

  const eventTypeLabel = (key: string) => eventTypes.find((e) => e.key === key)?.label || key
  const roleLabel = (id: number | null) => {
    if (!id) return '—'
    return roles.find((r) => r.id === id)?.name || `Role #${id}`
  }

  const columns = useMemo<ColumnDef<NotificationRule>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
      },
      {
        accessorKey: 'event_type',
        header: 'Event Type',
        cell: ({ row }) => (
          <Badge variant="outline" className="text-xs">{eventTypeLabel(row.original.event_type)}</Badge>
        ),
      },
      {
        accessorKey: 'channel',
        header: 'Channel',
        cell: ({ row }) => (
          <Badge variant="secondary" className="text-xs gap-1">
            {channelIcon(row.original.channel)}
            {CHANNEL_LABELS[row.original.channel] || row.original.channel}
          </Badge>
        ),
      },
      {
        id: 'role',
        header: 'Role',
        cell: ({ row }) => (
          <span className="text-muted-foreground">{roleLabel(row.original.role_id)}</span>
        ),
      },
      {
        accessorKey: 'enabled',
        header: 'Enabled',
        cell: ({ row }) => (
          <Switch
            checked={row.original.enabled}
            onCheckedChange={() => handleToggle(row.original)}
            disabled={!canManage}
          />
        ),
      },
      {
        id: 'actions',
        cell: ({ row }) =>
          canManage ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => openEdit(row.original)}>
                  <Pencil className="mr-2 h-3 w-3" /> Edit
                </DropdownMenuItem>
                <DropdownMenuItem className="text-destructive" onClick={() => setDeleteRule(row.original)}>
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null,
      },
    ],
    [canManage, eventTypes, roles]
  )

  const ruleFormFields = (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Name</Label>
        <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Job failures to admins" />
      </div>
      <div className="space-y-2">
        <Label>Event Type</Label>
        <Select value={form.event_type} onValueChange={(v) => setForm({ ...form, event_type: v })}>
          <SelectTrigger><SelectValue placeholder="Select event type..." /></SelectTrigger>
          <SelectContent>
            {eventTypes.map((et) => (
              <SelectItem key={et.key} value={et.key}>{et.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label>Channel</Label>
        <Select value={form.channel} onValueChange={(v) => setForm({ ...form, channel: v, slack_channel_id: '' })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="in_app">In-App</SelectItem>
            <SelectItem value="email">Email</SelectItem>
            <SelectItem value="slack">Slack</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {form.channel === 'slack' && (
        <div className="space-y-2">
          <Label>Slack Channel</Label>
          <Select value={form.slack_channel_id} onValueChange={(v) => setForm({ ...form, slack_channel_id: v })}>
            <SelectTrigger><SelectValue placeholder="Select Slack channel..." /></SelectTrigger>
            <SelectContent>
              {slackChannels.filter((c) => c.enabled).map((c) => (
                <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      <div className="space-y-2">
        <Label>Role</Label>
        <Select value={form.role_id} onValueChange={(v) => setForm({ ...form, role_id: v })}>
          <SelectTrigger><SelectValue placeholder="All roles" /></SelectTrigger>
          <SelectContent>
            {roles.map((r) => (
              <SelectItem key={r.id} value={String(r.id)}>{r.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label>Filters (JSON, optional)</Label>
        <Textarea
          value={form.filters}
          onChange={(e) => setForm({ ...form, filters: e.target.value })}
          placeholder='{"service": "n8n-server"}'
          rows={3}
          className="font-mono text-xs"
        />
      </div>
      <div className="flex items-center gap-2">
        <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} />
        <Label>Enabled</Label>
      </div>
    </div>
  )

  return (
    <>
      <div className="flex justify-end mb-4">
        {canManage && (
          <Button size="sm" onClick={openCreate}>
            <Plus className="mr-2 h-4 w-4" /> Create Rule
          </Button>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : (
        <DataTable columns={columns} data={rules} searchKey="name" searchPlaceholder="Search rules..." />
      )}

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create Notification Rule</DialogTitle></DialogHeader>
          {ruleFormFields}
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name.trim() || !form.event_type || createMutation.isPending}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editRule} onOpenChange={() => setEditRule(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Edit Notification Rule</DialogTitle></DialogHeader>
          {ruleFormFields}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditRule(null)}>Cancel</Button>
            <Button onClick={handleUpdate} disabled={!form.name.trim() || !form.event_type || updateMutation.isPending}>
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
        description={`Permanently delete rule "${deleteRule?.name}"?`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => {
          if (deleteRule) {
            deleteMutation.mutate(deleteRule.id, {
              onSuccess: () => {
                setDeleteRule(null)
                toast.success('Rule deleted')
              },
              onError: () => toast.error('Delete failed'),
            })
          }
        }}
      />
    </>
  )
}

// ─── Channels Tab ────────────────────────────────────────────────────────────

interface ChannelFormState {
  name: string
  type: string
  webhook_url: string
  enabled: boolean
}

const emptyChannelForm: ChannelFormState = {
  name: '',
  type: 'slack',
  webhook_url: '',
  enabled: true,
}

function ChannelsTab() {
  const canManage = useHasPermission('notifications.channels.manage')
  const { data: channelsData, isLoading } = useNotificationChannels()
  const channels = channelsData?.channels || []

  const [createOpen, setCreateOpen] = useState(false)
  const [editChannel, setEditChannel] = useState<NotificationChannel | null>(null)
  const [deleteChannel, setDeleteChannel] = useState<NotificationChannel | null>(null)
  const [form, setForm] = useState<ChannelFormState>(emptyChannelForm)

  const createMutation = useCreateChannel()
  const updateMutation = useUpdateChannel()
  const deleteMutation = useDeleteChannel()
  const testMutation = useTestChannel()

  function openCreate() {
    setForm(emptyChannelForm)
    setCreateOpen(true)
  }

  function openEdit(ch: NotificationChannel) {
    setForm({
      name: ch.name,
      type: ch.type,
      webhook_url: ch.config.webhook_url || '',
      enabled: ch.enabled,
    })
    setEditChannel(ch)
  }

  function handleCreate() {
    createMutation.mutate(
      { name: form.name, type: form.type, config: { webhook_url: form.webhook_url }, enabled: form.enabled },
      {
        onSuccess: () => {
          setCreateOpen(false)
          setForm(emptyChannelForm)
          toast.success('Channel created')
        },
        onError: (err: any) => toast.error(err.response?.data?.detail || 'Create failed'),
      }
    )
  }

  function handleUpdate() {
    if (!editChannel) return
    updateMutation.mutate(
      { id: editChannel.id, name: form.name, type: form.type, config: { webhook_url: form.webhook_url }, enabled: form.enabled },
      {
        onSuccess: () => {
          setEditChannel(null)
          toast.success('Channel updated')
        },
        onError: (err: any) => toast.error(err.response?.data?.detail || 'Update failed'),
      }
    )
  }

  function handleTest(id: number) {
    testMutation.mutate(id, {
      onSuccess: () => toast.success('Test notification sent'),
      onError: (err: any) => toast.error(err.response?.data?.detail || 'Test failed'),
    })
  }

  const columns = useMemo<ColumnDef<NotificationChannel>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
      },
      {
        accessorKey: 'type',
        header: 'Type',
        cell: ({ row }) => (
          <Badge variant="secondary" className="text-xs gap-1">
            <Hash className="h-3 w-3" />
            {row.original.type.charAt(0).toUpperCase() + row.original.type.slice(1)}
          </Badge>
        ),
      },
      {
        accessorKey: 'enabled',
        header: 'Enabled',
        cell: ({ row }) => (
          <Badge variant={row.original.enabled ? 'success' : 'secondary'}>
            {row.original.enabled ? 'Active' : 'Disabled'}
          </Badge>
        ),
      },
      {
        id: 'actions',
        cell: ({ row }) =>
          canManage ? (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleTest(row.original.id)}
                disabled={!row.original.enabled || testMutation.isPending}
              >
                <Send className="mr-1 h-3 w-3" /> Test
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-7 w-7">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => openEdit(row.original)}>
                    <Pencil className="mr-2 h-3 w-3" /> Edit
                  </DropdownMenuItem>
                  <DropdownMenuItem className="text-destructive" onClick={() => setDeleteChannel(row.original)}>
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ) : null,
      },
    ],
    [canManage, testMutation.isPending]
  )

  const channelFormFields = (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Name</Label>
        <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. #alerts channel" />
      </div>
      <div className="space-y-2">
        <Label>Type</Label>
        <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="slack">Slack</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label>Webhook URL</Label>
        <Input
          value={form.webhook_url}
          onChange={(e) => setForm({ ...form, webhook_url: e.target.value })}
          placeholder="https://hooks.slack.com/services/..."
          type="url"
        />
      </div>
      <div className="flex items-center gap-2">
        <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} />
        <Label>Enabled</Label>
      </div>
    </div>
  )

  return (
    <>
      <div className="flex justify-end mb-4">
        {canManage && (
          <Button size="sm" onClick={openCreate}>
            <Plus className="mr-2 h-4 w-4" /> Add Channel
          </Button>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : (
        <DataTable columns={columns} data={channels} searchKey="name" searchPlaceholder="Search channels..." />
      )}

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add Notification Channel</DialogTitle></DialogHeader>
          {channelFormFields}
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name.trim() || !form.webhook_url.trim() || createMutation.isPending}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editChannel} onOpenChange={() => setEditChannel(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Edit Notification Channel</DialogTitle></DialogHeader>
          {channelFormFields}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditChannel(null)}>Cancel</Button>
            <Button onClick={handleUpdate} disabled={!form.name.trim() || !form.webhook_url.trim() || updateMutation.isPending}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteChannel}
        onOpenChange={() => setDeleteChannel(null)}
        title="Delete Channel"
        description={`Permanently delete channel "${deleteChannel?.name}"? Rules using this channel will stop sending Slack notifications.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => {
          if (deleteChannel) {
            deleteMutation.mutate(deleteChannel.id, {
              onSuccess: () => {
                setDeleteChannel(null)
                toast.success('Channel deleted')
              },
              onError: () => toast.error('Delete failed'),
            })
          }
        }}
      />
    </>
  )
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function NotificationRulesPage() {
  return (
    <div>
      <PageHeader title="Notifications" description="Configure notification rules and channels" />
      <Tabs defaultValue="rules" className="mt-4">
        <TabsList>
          <TabsTrigger value="rules">Notification Rules</TabsTrigger>
          <TabsTrigger value="channels">Channels</TabsTrigger>
        </TabsList>
        <TabsContent value="rules">
          <RulesTab />
        </TabsContent>
        <TabsContent value="channels">
          <ChannelsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
