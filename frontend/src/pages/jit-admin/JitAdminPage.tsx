import { useState, useEffect, useRef } from 'react'
import { ShieldCheck, Clock, CheckCircle2, XCircle, AlertTriangle, ChevronLeft, ChevronRight, RefreshCw, Search, Users } from 'lucide-react'
import { toast } from 'sonner'
import { PageHeader } from '@/components/shared/PageHeader'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useHasPermission } from '@/lib/permissions'
import {
  useJitGrants,
  useJitHistory,
  useJitConfig,
  useCreateJitGrant,
  useAdminJitGrant,
  useApproveJitGrant,
  useDenyJitGrant,
  useRevokeJitGrant,
  useAdUsers,
  useAdGroups,
  useAdSync,
  type JitGrant,
  type AdUserEntry,
} from '@/hooks/useJitAdmin'

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} minutes`
  const hrs = minutes / 60
  return hrs === 1 ? '1 hour' : `${hrs} hours`
}

function formatTimeRemaining(expiresAt: string | null): string {
  if (!expiresAt) return '—'
  const now = Date.now()
  const exp = new Date(expiresAt).getTime()
  const diff = exp - now
  if (diff <= 0) return 'Expired'
  const mins = Math.floor(diff / 60000)
  const hrs = Math.floor(mins / 60)
  const remainMins = mins % 60
  if (hrs > 0) return `${hrs}h ${remainMins}m`
  return `${mins}m`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function statusVariant(status: string): string {
  switch (status) {
    case 'active': return 'running'
    case 'pending_approval': return 'warning'
    case 'expired': return 'secondary'
    case 'revoked': return 'secondary'
    case 'denied': return 'destructive'
    case 'failed': return 'destructive'
    default: return 'default'
  }
}

function workflowLabel(workflow: string): string {
  switch (workflow) {
    case 'self_service': return 'Self-Service'
    case 'request_approval': return 'Request + Approval'
    case 'admin_grant': return 'Admin Grant'
    default: return workflow
  }
}

// ─── AD User Combobox ───
function AdUserCombobox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [search, setSearch] = useState(value)
  const [open, setOpen] = useState(false)
  const { data: users } = useAdUsers(search)
  const inputRef = useRef<HTMLInputElement>(null)

  // Keep search in sync with external value changes
  useEffect(() => {
    setSearch(value)
  }, [value])

  const hasUsers = users && users.length > 0

  return (
    <Popover open={open && hasUsers} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            ref={inputRef}
            placeholder="Search AD users..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              onChange(e.target.value)
              setOpen(true)
            }}
            onFocus={() => setOpen(true)}
            className="pl-9"
          />
        </div>
      </PopoverTrigger>
      <PopoverContent
        className="w-[var(--radix-popover-trigger-width)] p-0"
        align="start"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <div className="max-h-[200px] overflow-y-auto">
          {users?.map((u) => (
            <button
              key={u.sam_account_name}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent transition-colors"
              onClick={() => {
                onChange(u.sam_account_name)
                setSearch(u.sam_account_name)
                setOpen(false)
              }}
            >
              <Users className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <span className="font-mono">{u.sam_account_name}</span>
              {u.display_name && (
                <span className="text-muted-foreground truncate">— {u.display_name}</span>
              )}
              {!u.enabled && (
                <Badge variant="secondary" className="ml-auto text-[10px] py-0">Disabled</Badge>
              )}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}

// ─── Live AD Group Select ───
function LiveGroupSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { data: liveGroups } = useAdGroups()
  const { data: config } = useJitConfig()
  const staticGroups = config?.groups ?? []

  // Merge: use live groups if available, fallback to static
  const groups = liveGroups && liveGroups.length > 0
    ? liveGroups
    : staticGroups.map((g) => ({ name: g, member_count: 0 }))

  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger>
        <SelectValue placeholder="Select AD group" />
      </SelectTrigger>
      <SelectContent>
        {groups.map((g) => (
          <SelectItem key={typeof g === 'string' ? g : g.name} value={typeof g === 'string' ? g : g.name}>
            <span className="flex items-center gap-2">
              {typeof g === 'string' ? g : g.name}
              {typeof g !== 'string' && g.member_count > 0 && (
                <span className="text-xs text-muted-foreground">({g.member_count} members)</span>
              )}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

// ─── Active Grants Tab ───
function ActiveGrantsTab() {
  const { data: grants, isLoading } = useJitGrants('active')
  const revokeMutation = useRevokeJitGrant()
  const [, setTick] = useState(0)

  // Tick every 15s to update countdown timers
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 15000)
    return () => clearInterval(interval)
  }, [])

  if (isLoading) return <Skeleton className="h-48 w-full" />

  if (!grants?.length) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
          <ShieldCheck className="h-10 w-10 mb-3 opacity-40" />
          <p className="text-sm">No active JIT grants</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>User</TableHead>
          <TableHead>AD Group</TableHead>
          <TableHead>Workflow</TableHead>
          <TableHead>Time Remaining</TableHead>
          <TableHead>Granted By</TableHead>
          <TableHead>Activated</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {grants.map((g) => (
          <TableRow key={g.id}>
            <TableCell className="font-mono text-sm">{g.target_username}</TableCell>
            <TableCell><Badge variant="outline">{g.ad_group}</Badge></TableCell>
            <TableCell className="text-xs text-muted-foreground">{workflowLabel(g.workflow)}</TableCell>
            <TableCell>
              <div className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-sm font-medium">{formatTimeRemaining(g.expires_at)}</span>
              </div>
            </TableCell>
            <TableCell className="text-sm">{g.requested_by_username}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{formatDate(g.activated_at)}</TableCell>
            <TableCell className="text-right">
              <Button
                variant="destructive"
                size="sm"
                disabled={revokeMutation.isPending}
                onClick={() => {
                  revokeMutation.mutate(g.id, {
                    onSuccess: () => toast.success('Grant revoked'),
                    onError: (e: any) => toast.error(e.response?.data?.detail || 'Revoke failed'),
                  })
                }}
              >
                Revoke
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

// ─── Request Form Tab ───
function RequestAccessTab() {
  const { data: config } = useJitConfig()
  const createMutation = useCreateJitGrant()
  const durations = config?.durations ?? [60]
  const canSelfService = useHasPermission('jit.self_service')
  const canRequest = useHasPermission('jit.request')

  const [username, setUsername] = useState('')
  const [group, setGroup] = useState('')
  const [duration, setDuration] = useState('60')
  const [reason, setReason] = useState('')
  const [workflow, setWorkflow] = useState<'self_service' | 'request_approval'>(
    canSelfService ? 'self_service' : 'request_approval'
  )

  const handleSubmit = () => {
    createMutation.mutate(
      {
        target_username: username,
        ad_group: group,
        duration_minutes: parseInt(duration),
        reason: reason || undefined,
        workflow,
      },
      {
        onSuccess: (data) => {
          toast.success(
            workflow === 'self_service'
              ? `Access granted — expires in ${duration}m`
              : 'Request submitted for approval'
          )
          setUsername('')
          setGroup('')
          setDuration('60')
          setReason('')
        },
        onError: (e: any) => toast.error(e.response?.data?.detail || 'Request failed'),
      }
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Request Temporary AD Access</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>AD Username</Label>
            <AdUserCombobox value={username} onChange={setUsername} />
          </div>
          <div className="space-y-2">
            <Label>AD Group</Label>
            <LiveGroupSelect value={group} onChange={setGroup} />
          </div>
          <div className="space-y-2">
            <Label>Duration</Label>
            <Select value={duration} onValueChange={setDuration}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {durations.map((d) => (
                  <SelectItem key={d} value={String(d)}>{formatDuration(d)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Workflow</Label>
            <Select value={workflow} onValueChange={(v) => setWorkflow(v as any)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {canSelfService && <SelectItem value="self_service">Self-Service (immediate)</SelectItem>}
                {canRequest && <SelectItem value="request_approval">Request + Approval</SelectItem>}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="space-y-2">
          <Label>Reason (optional)</Label>
          <Textarea
            placeholder="Why do you need this access?"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
          />
        </div>
        <div className="flex justify-end">
          <Button
            onClick={handleSubmit}
            disabled={!username || !group || createMutation.isPending}
          >
            {createMutation.isPending
              ? 'Submitting...'
              : workflow === 'self_service'
                ? 'Grant Access'
                : 'Submit Request'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Approval Queue Tab ───
function ApprovalQueueTab() {
  const { data: grants, isLoading } = useJitGrants('pending_approval')
  const approveMutation = useApproveJitGrant()
  const denyMutation = useDenyJitGrant()
  const [denyTarget, setDenyTarget] = useState<JitGrant | null>(null)
  const [denyReason, setDenyReason] = useState('')

  if (isLoading) return <Skeleton className="h-48 w-full" />

  if (!grants?.length) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
          <CheckCircle2 className="h-10 w-10 mb-3 opacity-40" />
          <p className="text-sm">No pending requests</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>User</TableHead>
            <TableHead>AD Group</TableHead>
            <TableHead>Duration</TableHead>
            <TableHead>Reason</TableHead>
            <TableHead>Requested By</TableHead>
            <TableHead>Requested At</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {grants.map((g) => (
            <TableRow key={g.id}>
              <TableCell className="font-mono text-sm">{g.target_username}</TableCell>
              <TableCell><Badge variant="outline">{g.ad_group}</Badge></TableCell>
              <TableCell className="text-sm">{g.duration_minutes}m</TableCell>
              <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate">
                {g.reason || '—'}
              </TableCell>
              <TableCell className="text-sm">{g.requested_by_username}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{formatDate(g.requested_at)}</TableCell>
              <TableCell className="text-right space-x-2">
                <Button
                  size="sm"
                  disabled={approveMutation.isPending}
                  onClick={() =>
                    approveMutation.mutate(g.id, {
                      onSuccess: () => toast.success('Request approved'),
                      onError: (e: any) => toast.error(e.response?.data?.detail || 'Approve failed'),
                    })
                  }
                >
                  Approve
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => { setDenyTarget(g); setDenyReason('') }}
                >
                  Deny
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={!!denyTarget} onOpenChange={(open) => { if (!open) setDenyTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Deny JIT Request</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Denying access for <span className="font-mono">{denyTarget?.target_username}</span> to{' '}
            <span className="font-medium">{denyTarget?.ad_group}</span>
          </p>
          <div className="space-y-2">
            <Label>Reason (optional)</Label>
            <Textarea
              placeholder="Why is this request being denied?"
              value={denyReason}
              onChange={(e) => setDenyReason(e.target.value)}
              rows={2}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDenyTarget(null)}>Cancel</Button>
            <Button
              variant="destructive"
              disabled={denyMutation.isPending}
              onClick={() => {
                if (!denyTarget) return
                denyMutation.mutate(
                  { grantId: denyTarget.id, reason: denyReason || undefined },
                  {
                    onSuccess: () => { toast.success('Request denied'); setDenyTarget(null) },
                    onError: (e: any) => toast.error(e.response?.data?.detail || 'Deny failed'),
                  }
                )
              }}
            >
              {denyMutation.isPending ? 'Denying...' : 'Deny'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ─── Admin Grant Tab ───
function AdminGrantTab() {
  const { data: config } = useJitConfig()
  const adminMutation = useAdminJitGrant()
  const durations = config?.durations ?? [60]

  const [username, setUsername] = useState('')
  const [group, setGroup] = useState('')
  const [duration, setDuration] = useState('60')
  const [reason, setReason] = useState('')

  const handleSubmit = () => {
    adminMutation.mutate(
      {
        target_username: username,
        ad_group: group,
        duration_minutes: parseInt(duration),
        reason: reason || undefined,
      },
      {
        onSuccess: () => {
          toast.success(`Admin grant created — expires in ${duration}m`)
          setUsername('')
          setGroup('')
          setDuration('60')
          setReason('')
        },
        onError: (e: any) => toast.error(e.response?.data?.detail || 'Grant failed'),
      }
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Grant AD Access to User</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Target AD Username</Label>
            <AdUserCombobox value={username} onChange={setUsername} />
          </div>
          <div className="space-y-2">
            <Label>AD Group</Label>
            <LiveGroupSelect value={group} onChange={setGroup} />
          </div>
          <div className="space-y-2">
            <Label>Duration</Label>
            <Select value={duration} onValueChange={setDuration}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {durations.map((d) => (
                  <SelectItem key={d} value={String(d)}>{formatDuration(d)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="space-y-2">
          <Label>Reason (optional)</Label>
          <Textarea
            placeholder="Why is this access being granted?"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
          />
        </div>
        <div className="flex justify-end">
          <Button
            onClick={handleSubmit}
            disabled={!username || !group || adminMutation.isPending}
          >
            {adminMutation.isPending ? 'Granting...' : 'Grant Access'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── History Tab ───
function HistoryTab() {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useJitHistory(page)

  if (isLoading) return <Skeleton className="h-48 w-full" />

  const grants = data?.grants ?? []
  const total = data?.total ?? 0
  const pageSize = data?.page_size ?? 25
  const totalPages = Math.ceil(total / pageSize)

  if (!grants.length) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
          <Clock className="h-10 w-10 mb-3 opacity-40" />
          <p className="text-sm">No history yet</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>User</TableHead>
            <TableHead>AD Group</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Workflow</TableHead>
            <TableHead>Duration</TableHead>
            <TableHead>Requested By</TableHead>
            <TableHead>Date</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {grants.map((g) => (
            <TableRow key={g.id}>
              <TableCell className="font-mono text-sm">{g.target_username}</TableCell>
              <TableCell><Badge variant="outline">{g.ad_group}</Badge></TableCell>
              <TableCell>
                <Badge variant={statusVariant(g.status) as any}>
                  {g.status.replace('_', ' ')}
                </Badge>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">{workflowLabel(g.workflow)}</TableCell>
              <TableCell className="text-sm">{g.duration_minutes}m</TableCell>
              <TableCell className="text-sm">{g.requested_by_username}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{formatDate(g.requested_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {totalPages > 1 && (
        <div className="flex items-center justify-between px-2">
          <p className="text-sm text-muted-foreground">
            {total} total grant{total !== 1 ? 's' : ''}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-sm text-muted-foreground">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Main Page ───
export default function JitAdminPage() {
  const canApprove = useHasPermission('jit.approve')
  const canAdminGrant = useHasPermission('jit.admin_grant')
  const { data: activeGrants } = useJitGrants('active')
  const { data: pendingGrants } = useJitGrants('pending_approval')
  const { data: liveGroups } = useAdGroups()
  const syncMutation = useAdSync()

  const activeCount = activeGrants?.length ?? 0
  const pendingCount = pendingGrants?.length ?? 0

  // Get last sync time from the first live group's synced_at
  const lastSyncAt = liveGroups?.[0]?.synced_at
    ? new Date(liveGroups[0].synced_at).toLocaleString()
    : null

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="JIT Administration"
        description="Temporary elevated AD group membership with automatic revocation"
      >
        {canAdminGrant && (
          <div className="flex items-center gap-3">
            {lastSyncAt && (
              <span className="text-xs text-muted-foreground">
                Last sync: {lastSyncAt}
              </span>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                syncMutation.mutate(undefined, {
                  onSuccess: (data) => {
                    if (data.skipped) {
                      toast.info('Sync already in progress')
                    } else if (data.error) {
                      toast.error(`Sync failed: ${data.error}`)
                    } else {
                      toast.success(`Synced ${data.users} users, ${data.groups} groups`)
                    }
                  },
                  onError: (e: any) => toast.error(e.response?.data?.detail || 'Sync failed'),
                })
              }
              disabled={syncMutation.isPending}
            >
              <RefreshCw className={`h-4 w-4 mr-1.5 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
              {syncMutation.isPending ? 'Syncing...' : 'Refresh Directory'}
            </Button>
          </div>
        )}
      </PageHeader>

      <Tabs defaultValue="active">
        <TabsList>
          <TabsTrigger value="active" className="gap-1.5">
            Active
            {activeCount > 0 && (
              <Badge variant="running" className="ml-1 h-5 min-w-[20px] px-1.5 text-xs">
                {activeCount}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="request">Request Access</TabsTrigger>
          {canApprove && (
            <TabsTrigger value="approval" className="gap-1.5">
              Approval Queue
              {pendingCount > 0 && (
                <Badge variant="warning" className="ml-1 h-5 min-w-[20px] px-1.5 text-xs">
                  {pendingCount}
                </Badge>
              )}
            </TabsTrigger>
          )}
          {canAdminGrant && <TabsTrigger value="admin">Admin Grant</TabsTrigger>}
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>

        <TabsContent value="active" className="mt-4">
          <ActiveGrantsTab />
        </TabsContent>
        <TabsContent value="request" className="mt-4">
          <RequestAccessTab />
        </TabsContent>
        {canApprove && (
          <TabsContent value="approval" className="mt-4">
            <ApprovalQueueTab />
          </TabsContent>
        )}
        {canAdminGrant && (
          <TabsContent value="admin" className="mt-4">
            <AdminGrantTab />
          </TabsContent>
        )}
        <TabsContent value="history" className="mt-4">
          <HistoryTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
