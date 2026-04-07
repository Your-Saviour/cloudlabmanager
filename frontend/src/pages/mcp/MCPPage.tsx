import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Bot, Play, Square, RefreshCw, Loader2, Trash2, Clock, Server,
  Settings, ScrollText, Shield, Plus, X, Copy, Check,
} from 'lucide-react'
import { toast } from 'sonner'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { PageHeader } from '@/components/shared/PageHeader'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'

interface MCPConfig {
  enabled: boolean
  auto_restart: boolean
  allowed_services: string[]
  max_concurrent: number
  default_ttl_hours: number
  max_ttl_hours: number
  plan_limits: Record<string, string>
  sse_port: number
}

interface MCPStatus {
  running: boolean
  pid: number | null
  started_at: string | null
  uptime_seconds?: number
  restart_count: number
  enabled: boolean
}

interface MCPInstance {
  hostname: string
  ip_address: string
  region: string
  plan: string
  power_status: string
  service: string
  owner: string
  ttl_hours: number | null
  created_at: string | null
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function formatTimeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// --- Overview Tab ---
function OverviewTab({ status, config }: { status: MCPStatus | undefined; config: MCPConfig | undefined }) {
  const queryClient = useQueryClient()
  const [copied, setCopied] = useState(false)

  const startMutation = useMutation({
    mutationFn: () => api.post('/api/mcp/start'),
    onSuccess: () => {
      toast.success('MCP server started')
      queryClient.invalidateQueries({ queryKey: ['mcp-status'] })
    },
    onError: () => toast.error('Failed to start MCP server'),
  })

  const stopMutation = useMutation({
    mutationFn: () => api.post('/api/mcp/stop'),
    onSuccess: () => {
      toast.success('MCP server stopped')
      queryClient.invalidateQueries({ queryKey: ['mcp-status'] })
    },
    onError: () => toast.error('Failed to stop MCP server'),
  })

  const { data: instances } = useQuery({
    queryKey: ['mcp-instances'],
    queryFn: async () => {
      const { data } = await api.get('/api/mcp/instances')
      return data.instances as MCPInstance[]
    },
  })

  const claudeConfig = JSON.stringify({
    mcpServers: {
      cloudlab: {
        command: 'docker',
        args: ['compose', 'exec', 'cloudlabmanager', 'python3', '-m', 'mcp_server', '--transport', 'stdio'],
      },
    },
  }, null, 2)

  const handleCopy = () => {
    navigator.clipboard.writeText(claudeConfig)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-4 w-4" />
            Process Status
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Status</span>
            <Badge variant={status?.running ? 'default' : 'secondary'}>
              {status?.running ? 'Running' : 'Stopped'}
            </Badge>
          </div>
          {status?.pid && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">PID</span>
              <span className="text-sm font-mono">{status.pid}</span>
            </div>
          )}
          {status?.uptime_seconds !== undefined && status.running && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Uptime</span>
              <span className="text-sm">{formatUptime(status.uptime_seconds)}</span>
            </div>
          )}
          {status?.restart_count !== undefined && status.restart_count > 0 && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Restarts</span>
              <span className="text-sm">{status.restart_count}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Active Instances</span>
            <Badge variant="outline">{instances?.length ?? 0} / {config?.max_concurrent ?? 3}</Badge>
          </div>
          <div className="flex gap-2 pt-2">
            {status?.running ? (
              <Button
                variant="destructive"
                size="sm"
                onClick={() => stopMutation.mutate()}
                disabled={stopMutation.isPending}
              >
                {stopMutation.isPending ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <Square className="mr-2 h-3.5 w-3.5" />}
                Stop
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={() => startMutation.mutate()}
                disabled={startMutation.isPending}
              >
                {startMutation.isPending ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-2 h-3.5 w-3.5" />}
                Start
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-4 w-4" />
            Claude Code Config
          </CardTitle>
          <CardDescription>Add this to your Claude Desktop config or use the CLI command</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative">
            <pre className="bg-muted p-3 rounded-md text-xs font-mono overflow-x-auto max-h-48">
              {claudeConfig}
            </pre>
            <Button
              variant="ghost"
              size="icon"
              className="absolute top-2 right-2 h-6 w-6"
              onClick={handleCopy}
            >
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// --- Config Tab ---
function ConfigTab() {
  const queryClient = useQueryClient()

  const { data: config, isLoading } = useQuery({
    queryKey: ['mcp-config'],
    queryFn: async () => {
      const { data } = await api.get('/api/mcp/config')
      return data as MCPConfig
    },
  })

  const [form, setForm] = useState<MCPConfig | null>(null)
  const [newService, setNewService] = useState('')
  const [newPlanService, setNewPlanService] = useState('')
  const [newPlanValue, setNewPlanValue] = useState('')

  useEffect(() => {
    if (config && !form) setForm({ ...config })
  }, [config])

  const saveMutation = useMutation({
    mutationFn: (data: Partial<MCPConfig>) => api.put('/api/mcp/config', data),
    onSuccess: () => {
      toast.success('MCP config saved')
      queryClient.invalidateQueries({ queryKey: ['mcp-config'] })
    },
    onError: () => toast.error('Failed to save config'),
  })

  if (isLoading || !form) {
    return <div className="space-y-4"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /></div>
  }

  const addService = () => {
    if (newService && !form.allowed_services.includes(newService)) {
      setForm({ ...form, allowed_services: [...form.allowed_services, newService] })
      setNewService('')
    }
  }

  const removeService = (s: string) => {
    setForm({ ...form, allowed_services: form.allowed_services.filter((x) => x !== s) })
  }

  const addPlanLimit = () => {
    if (newPlanService && newPlanValue) {
      setForm({ ...form, plan_limits: { ...form.plan_limits, [newPlanService]: newPlanValue } })
      setNewPlanService('')
      setNewPlanValue('')
    }
  }

  const removePlanLimit = (key: string) => {
    if (key === 'default') return
    const { [key]: _, ...rest } = form.plan_limits
    setForm({ ...form, plan_limits: rest })
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle>General</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="auto-restart">Auto-restart on crash</Label>
            <Switch
              id="auto-restart"
              checked={form.auto_restart}
              onCheckedChange={(v) => setForm({ ...form, auto_restart: v })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="max-concurrent">Max concurrent instances</Label>
            <Input
              id="max-concurrent"
              type="number"
              min={1}
              max={20}
              value={form.max_concurrent}
              onChange={(e) => setForm({ ...form, max_concurrent: parseInt(e.target.value) || 3 })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="default-ttl">Default TTL (hours)</Label>
              <Input
                id="default-ttl"
                type="number"
                min={1}
                max={168}
                value={form.default_ttl_hours}
                onChange={(e) => setForm({ ...form, default_ttl_hours: parseInt(e.target.value) || 4 })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="max-ttl">Max TTL (hours)</Label>
              <Input
                id="max-ttl"
                type="number"
                min={1}
                max={168}
                value={form.max_ttl_hours}
                onChange={(e) => setForm({ ...form, max_ttl_hours: parseInt(e.target.value) || 8 })}
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="sse-port">SSE Port</Label>
            <Input
              id="sse-port"
              type="number"
              value={form.sse_port}
              onChange={(e) => setForm({ ...form, sse_port: parseInt(e.target.value) || 8765 })}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Allowed Services</CardTitle>
          <CardDescription>Services the MCP server can create instances from</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {form.allowed_services.map((s) => (
              <Badge key={s} variant="secondary" className="gap-1">
                {s}
                <button onClick={() => removeService(s)} className="ml-1 hover:text-destructive">
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
            {form.allowed_services.length === 0 && (
              <span className="text-sm text-muted-foreground">No services allowed</span>
            )}
          </div>
          <div className="flex gap-2">
            <Input
              placeholder="Service name (e.g., personal-linux-vm)"
              value={newService}
              onChange={(e) => setNewService(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addService()}
            />
            <Button variant="outline" size="icon" onClick={addService}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Plan Limits</CardTitle>
          <CardDescription>Maximum Vultr plan per service (by monthly cost)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Service</TableHead>
                <TableHead>Max Plan</TableHead>
                <TableHead className="w-10"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(form.plan_limits).map(([key, val]) => (
                <TableRow key={key}>
                  <TableCell className="font-mono text-sm">{key}</TableCell>
                  <TableCell className="font-mono text-sm">{val}</TableCell>
                  <TableCell>
                    {key !== 'default' && (
                      <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => removePlanLimit(key)}>
                        <X className="h-3 w-3" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="flex gap-2">
            <Input
              placeholder="Service name"
              value={newPlanService}
              onChange={(e) => setNewPlanService(e.target.value)}
              className="flex-1"
            />
            <Input
              placeholder="vc2-1c-1gb"
              value={newPlanValue}
              onChange={(e) => setNewPlanValue(e.target.value)}
              className="flex-1"
            />
            <Button variant="outline" size="icon" onClick={addPlanLimit}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </CardContent>
      </Card>

      <Button
        onClick={() => saveMutation.mutate(form)}
        disabled={saveMutation.isPending}
      >
        {saveMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        Save Configuration
      </Button>
    </div>
  )
}

// --- Instances Tab ---
function InstancesTab() {
  const queryClient = useQueryClient()

  const { data: instances, isLoading } = useQuery({
    queryKey: ['mcp-instances'],
    queryFn: async () => {
      const { data } = await api.get('/api/mcp/instances')
      return data.instances as MCPInstance[]
    },
    refetchInterval: 10000,
  })

  const destroyMutation = useMutation({
    mutationFn: (hostname: string) => api.delete(`/api/mcp/instances/${hostname}`),
    onSuccess: () => {
      toast.success('Instance destroy initiated')
      queryClient.invalidateQueries({ queryKey: ['mcp-instances'] })
    },
    onError: () => toast.error('Failed to destroy instance'),
  })

  if (isLoading) {
    return <div className="space-y-2"><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /></div>
  }

  if (!instances?.length) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground">
          No MCP-created instances are currently active.
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Hostname</TableHead>
            <TableHead>Service</TableHead>
            <TableHead>Region</TableHead>
            <TableHead>Plan</TableHead>
            <TableHead>IP</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>TTL</TableHead>
            <TableHead>Created</TableHead>
            <TableHead className="w-10"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {instances.map((inst) => (
            <TableRow key={inst.hostname}>
              <TableCell className="font-mono text-sm">{inst.hostname}</TableCell>
              <TableCell>{inst.service}</TableCell>
              <TableCell>{inst.region}</TableCell>
              <TableCell className="font-mono text-sm">{inst.plan}</TableCell>
              <TableCell className="font-mono text-sm">{inst.ip_address}</TableCell>
              <TableCell>
                <Badge variant={inst.power_status === 'running' ? 'default' : 'secondary'}>
                  {inst.power_status}
                </Badge>
              </TableCell>
              <TableCell>{inst.ttl_hours ? `${inst.ttl_hours}h` : '-'}</TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {inst.created_at ? formatTimeAgo(inst.created_at) : '-'}
              </TableCell>
              <TableCell>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive">
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Destroy instance?</AlertDialogTitle>
                      <AlertDialogDescription>
                        This will permanently destroy <span className="font-mono font-bold">{inst.hostname}</span>.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => destroyMutation.mutate(inst.hostname)}
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      >
                        Destroy
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}

// --- Logs Tab ---
function LogsTab() {
  const { data: logs, isLoading, refetch } = useQuery({
    queryKey: ['mcp-logs'],
    queryFn: async () => {
      const { data } = await api.get('/api/mcp/logs?lines=200')
      return data.lines as string[]
    },
    refetchInterval: 5000,
  })

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base">Server Logs</CardTitle>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => refetch()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <pre className="bg-muted p-4 rounded-md text-xs font-mono overflow-auto max-h-[600px] whitespace-pre-wrap">
            {logs?.length ? logs.join('\n') : 'No logs available. Start the MCP server to see output.'}
          </pre>
        )}
      </CardContent>
    </Card>
  )
}

// --- Main Page ---
export default function MCPPage() {
  const canManage = useHasPermission('mcp.manage')

  const { data: status } = useQuery({
    queryKey: ['mcp-status'],
    queryFn: async () => {
      const { data } = await api.get('/api/mcp/status')
      return data as MCPStatus
    },
    refetchInterval: 5000,
    enabled: canManage,
  })

  const { data: config } = useQuery({
    queryKey: ['mcp-config'],
    queryFn: async () => {
      const { data } = await api.get('/api/mcp/config')
      return data as MCPConfig
    },
    enabled: canManage,
  })

  if (!canManage) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        You do not have permission to manage the MCP server.
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="MCP Server"
        description="Manage the Model Context Protocol server for AI agent access to CloudLab"
      >
        <Badge variant={status?.running ? 'default' : 'secondary'} className="ml-2">
          {status?.running ? 'Running' : 'Stopped'}
        </Badge>
      </PageHeader>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview" className="gap-1.5">
            <Server className="h-3.5 w-3.5" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="config" className="gap-1.5">
            <Settings className="h-3.5 w-3.5" />
            Config
          </TabsTrigger>
          <TabsTrigger value="instances" className="gap-1.5">
            <Shield className="h-3.5 w-3.5" />
            Instances
          </TabsTrigger>
          <TabsTrigger value="logs" className="gap-1.5">
            <ScrollText className="h-3.5 w-3.5" />
            Logs
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab status={status} config={config} />
        </TabsContent>
        <TabsContent value="config">
          <ConfigTab />
        </TabsContent>
        <TabsContent value="instances">
          <InstancesTab />
        </TabsContent>
        <TabsContent value="logs">
          <LogsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
