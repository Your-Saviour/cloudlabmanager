import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, DollarSign, Server, CreditCard, TrendingUp, TrendingDown, Minus, Save, AlertTriangle, Camera } from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { PageHeader } from '@/components/shared/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { toast } from 'sonner'
import type { CostData, CostHistoryResponse, CostSummary, CostServicePoint } from '@/types'

interface BudgetSettings {
  enabled: boolean
  monthly_threshold: number
  recipients: string[]
  alert_cooldown_hours: number
}

const CHART_COLORS = ['#f0a030', '#3b82f6', '#22c55e', '#ef4444', '#8b5cf6', '#ec4899']

const TIME_RANGES = [
  { label: '30d', value: 30 },
  { label: '90d', value: 90 },
  { label: '180d', value: 180 },
  { label: '1y', value: 365 },
]

function ChangeIndicator({ direction, percent }: { direction: 'up' | 'down' | 'flat'; percent: number }) {
  if (direction === 'flat') return <Minus className="h-3 w-3 text-muted-foreground" />
  const isUp = direction === 'up'
  const Icon = isUp ? TrendingUp : TrendingDown
  const color = isUp ? 'text-red-400' : 'text-green-400'
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${color}`}>
      <Icon className="h-3 w-3" />
      {Math.abs(percent).toFixed(1)}%
    </span>
  )
}

export default function CostsPage() {
  const queryClient = useQueryClient()
  const [days, setDays] = useState(90)

  const { data: costs, isLoading } = useQuery({
    queryKey: ['costs'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs')
      return data as CostData
    },
    refetchInterval: 60000,
  })

  const { data: byTag } = useQuery({
    queryKey: ['costs', 'by-tag'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs/by-tag')
      return data.by_tag as Record<string, number>
    },
  })

  const { data: byRegion } = useQuery({
    queryKey: ['costs', 'by-region'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs/by-region')
      return data.by_region as Record<string, number>
    },
  })

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ['costs', 'history', days],
    queryFn: async () => {
      const { data } = await api.get(`/api/costs/history?days=${days}`)
      return data as CostHistoryResponse
    },
    refetchInterval: 60000,
  })

  const { data: byService, isLoading: byServiceLoading } = useQuery({
    queryKey: ['costs', 'history', 'by-service'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs/history/by-service')
      return data as { data_points: CostServicePoint[] }
    },
    refetchInterval: 60000,
  })

  const { data: summary } = useQuery({
    queryKey: ['costs', 'summary'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs/summary')
      return data as CostSummary
    },
    refetchInterval: 60000,
  })

  const canManageBudget = useHasPermission('costs.budget')

  const { data: budgetSettings } = useQuery({
    queryKey: ['costs', 'budget'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs/budget')
      return data as BudgetSettings
    },
    enabled: canManageBudget,
  })

  const [budgetForm, setBudgetForm] = useState<BudgetSettings>({
    enabled: false,
    monthly_threshold: 0,
    recipients: [],
    alert_cooldown_hours: 24,
  })
  const [recipientsInput, setRecipientsInput] = useState('')

  useEffect(() => {
    if (budgetSettings) {
      setBudgetForm(budgetSettings)
      setRecipientsInput(budgetSettings.recipients?.join(', ') ?? '')
    }
  }, [budgetSettings])

  const budgetMutation = useMutation({
    mutationFn: (payload: BudgetSettings) => api.put('/api/costs/budget', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costs', 'budget'] })
      toast.success('Budget settings saved')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to save budget settings'),
  })

  const saveBudget = () => {
    const recipients = recipientsInput
      .split(',')
      .map((e) => e.trim())
      .filter((e) => e.length > 0)
    budgetMutation.mutate({ ...budgetForm, recipients })
  }

  const refreshMutation = useMutation({
    mutationFn: () => api.post('/api/costs/refresh'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costs'] })
      toast.success('Costs refreshed')
    },
    onError: () => toast.error('Refresh failed'),
  })

  // Collect all unique service names from by-service data for stacked bar chart
  const serviceNames = byService?.data_points
    ? [...new Set(byService.data_points.flatMap((p) => Object.keys(p.services)))]
    : []

  // Transform by-service data for recharts (flatten services into top-level keys)
  const barChartData = byService?.data_points?.map((p) => ({
    date: p.date,
    ...p.services,
  })) ?? []

  return (
    <div>
      <PageHeader title="Costs" description="Infrastructure cost breakdown">
        <Button
          variant="outline"
          size="sm"
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending}
        >
          <RefreshCw className={`mr-2 h-3 w-3 ${refreshMutation.isPending ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </PageHeader>

      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-6">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <DollarSign className="h-8 w-8 text-primary" />
              <div>
                <p className="text-sm text-muted-foreground">Monthly Total</p>
                {isLoading ? (
                  <Skeleton className="h-9 w-24" />
                ) : (
                  <div className="flex items-center gap-2">
                    <p className="text-3xl font-bold">
                      ${costs?.total_monthly_cost?.toFixed(2) || '0.00'}
                    </p>
                    {summary && <ChangeIndicator direction={summary.direction} percent={summary.change_percent} />}
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <Server className="h-8 w-8 text-primary" />
              <div>
                <p className="text-sm text-muted-foreground">Instance Count</p>
                {isLoading ? (
                  <Skeleton className="h-9 w-16" />
                ) : (
                  <div className="flex items-center gap-2">
                    <p className="text-3xl font-bold">{costs?.instances?.length ?? 0}</p>
                    {summary && summary.previous_instance_count !== summary.current_instance_count && (
                      <span className="text-xs text-muted-foreground">
                        was {summary.previous_instance_count}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <CreditCard className="h-8 w-8 text-primary" />
              <div>
                <p className="text-sm text-muted-foreground">Pending Charges</p>
                {isLoading ? (
                  <Skeleton className="h-9 w-24" />
                ) : (
                  <p className="text-3xl font-bold">
                    ${summary?.current_total?.toFixed(2) ?? costs?.total_monthly_cost?.toFixed(2) ?? '0.00'}
                  </p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {costs?.snapshot_storage && (
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-3">
                <Camera className="h-8 w-8 text-primary" />
                <div>
                  <p className="text-sm text-muted-foreground">Snapshot Storage</p>
                  <p className="text-3xl font-bold">
                    {costs.snapshot_storage.total_size_gb} GB
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {costs.snapshot_storage.snapshot_count} snapshots
                    {' · '}
                    ${costs.snapshot_storage.monthly_cost.toFixed(2)}/mo
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Line Chart — Total Spend Over Time */}
      <Card className="mb-6">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">Total Monthly Spend</CardTitle>
            <div className="flex gap-1">
              {TIME_RANGES.map((r) => (
                <Button
                  key={r.value}
                  variant={days === r.value ? 'default' : 'outline'}
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => setDays(r.value)}
                  aria-label={`Show last ${r.label === '1y' ? '1 year' : r.label.replace('d', ' days')}`}
                  aria-pressed={days === r.value}
                >
                  {r.label}
                </Button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {historyLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : !history?.data_points?.length ? (
            <p className="text-sm text-muted-foreground text-center py-16">No historical data yet</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={history.data_points}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2738" />
                <XAxis dataKey="date" stroke="#4a5a70" fontSize={12} />
                <YAxis stroke="#4a5a70" fontSize={12} tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  contentStyle={{ background: '#0a0c10', border: '1px solid #1e2738', borderRadius: 8 }}
                  labelStyle={{ color: '#8899b0' }}
                  formatter={(value: number | undefined) => [`$${(value ?? 0).toFixed(2)}`, 'Monthly Cost']}
                />
                <Line type="monotone" dataKey="total_monthly_cost" stroke="#f0a030" strokeWidth={2} dot={false} />
                {budgetSettings?.enabled && budgetSettings?.monthly_threshold > 0 && (
                  <ReferenceLine
                    y={budgetSettings.monthly_threshold}
                    stroke="#ef4444"
                    strokeDasharray="5 5"
                    label={{ value: `Budget: $${budgetSettings.monthly_threshold}`, position: 'right', fill: '#ef4444', fontSize: 12 }}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Stacked Bar Chart — Cost by Service */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-sm">Cost by Service</CardTitle>
        </CardHeader>
        <CardContent>
          {byServiceLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : !barChartData.length ? (
            <p className="text-sm text-muted-foreground text-center py-16">No historical data yet</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={barChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2738" />
                <XAxis dataKey="date" stroke="#4a5a70" fontSize={12} />
                <YAxis stroke="#4a5a70" fontSize={12} tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  contentStyle={{ background: '#0a0c10', border: '1px solid #1e2738', borderRadius: 8 }}
                  labelStyle={{ color: '#8899b0' }}
                  formatter={(value: number | undefined) => `$${(value ?? 0).toFixed(2)}`}
                />
                <Legend />
                {serviceNames.map((name, i) => (
                  <Bar
                    key={name}
                    dataKey={name}
                    stackId="services"
                    fill={CHART_COLORS[i % CHART_COLORS.length]}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Budget Settings */}
      {canManageBudget && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" /> Budget Alerts
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-2">
              <Switch
                id="budget-enabled"
                checked={budgetForm.enabled}
                onCheckedChange={(v) => setBudgetForm({ ...budgetForm, enabled: v })}
              />
              <Label htmlFor="budget-enabled" className="text-sm font-normal">Enable budget alerts</Label>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="budget-threshold">Monthly Threshold ($)</Label>
                <Input
                  id="budget-threshold"
                  type="number"
                  min={0}
                  step={1}
                  value={budgetForm.monthly_threshold || ''}
                  onChange={(e) => setBudgetForm({ ...budgetForm, monthly_threshold: parseFloat(e.target.value) || 0 })}
                  placeholder="150.00"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="budget-recipients">Alert Recipients (comma-separated)</Label>
                <Input
                  id="budget-recipients"
                  value={recipientsInput}
                  onChange={(e) => setRecipientsInput(e.target.value)}
                  placeholder="admin@example.com, ops@example.com"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="budget-cooldown">Cooldown (hours)</Label>
                <Input
                  id="budget-cooldown"
                  type="number"
                  min={1}
                  value={budgetForm.alert_cooldown_hours}
                  onChange={(e) => setBudgetForm({ ...budgetForm, alert_cooldown_hours: parseInt(e.target.value) || 24 })}
                />
              </div>
            </div>
            <Button size="sm" onClick={saveBudget} disabled={budgetMutation.isPending}>
              <Save className="mr-2 h-3 w-3" /> Save Budget Settings
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Existing Breakdown */}
      <div className="grid gap-6 lg:grid-cols-2 mb-6">
        {/* By Tag */}
        {byTag && Object.keys(byTag).length > 0 && (
          <Card>
            <CardHeader><CardTitle className="text-sm">By Tag</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                {Object.entries(byTag)
                  .sort(([, a], [, b]) => b - a)
                  .map(([tag, cost]) => (
                    <div key={tag} className="flex items-center justify-between">
                      <Badge variant="outline">{tag}</Badge>
                      <span className="font-mono text-sm">${cost.toFixed(2)}</span>
                    </div>
                  ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* By Region */}
        {byRegion && Object.keys(byRegion).length > 0 && (
          <Card>
            <CardHeader><CardTitle className="text-sm">By Region</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                {Object.entries(byRegion)
                  .sort(([, a], [, b]) => b - a)
                  .map(([region, cost]) => (
                    <div key={region} className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">{region}</span>
                      <span className="font-mono text-sm">${cost.toFixed(2)}</span>
                    </div>
                  ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Instances */}
      <Card>
        <CardHeader><CardTitle className="text-sm">Instances</CardTitle></CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : (!costs?.instances || costs.instances.length === 0) ? (
            <p className="text-sm text-muted-foreground text-center py-4">No instance data available</p>
          ) : (
            <div className="space-y-2">
              {costs.instances
                .sort((a, b) => b.monthly_cost - a.monthly_cost)
                .map((inst, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2 rounded-md hover:bg-muted/30">
                    <div>
                      <p className="text-sm font-medium">{inst.label}</p>
                      <p className="text-xs text-muted-foreground">
                        {inst.region} &middot; {inst.plan}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono text-sm">${inst.monthly_cost.toFixed(2)}/mo</p>
                      {inst.tags.length > 0 && (
                        <div className="flex gap-1 justify-end mt-1">
                          {inst.tags.map((t) => (
                            <Badge key={t} variant="outline" className="text-[10px]">{t}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
