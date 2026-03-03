import { useQuery } from '@tanstack/react-query'
import { Server, Play, Activity, DollarSign, CheckCircle, XCircle, Database, HeartPulse } from 'lucide-react'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { useInventoryStore } from '@/stores/inventoryStore'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { Job, Service } from '@/types'
import type { HealthSummary } from '@/types/health'

export function StatsWidget(_props: { config: Record<string, any> }) {
  const canViewCosts = useHasPermission('costs.view')
  const inventoryTypes = useInventoryStore((s) => s.types)

  const { data: jobs, isLoading: jobsLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => {
      const { data } = await api.get('/api/jobs')
      return (data.jobs || []) as Job[]
    },
    refetchInterval: 5000,
  })

  const { data: services } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const { data } = await api.get('/api/services')
      return (data.services || []) as Service[]
    },
    refetchInterval: 10000,
  })

  const { data: deployments } = useQuery({
    queryKey: ['active-deployments'],
    queryFn: async () => {
      const { data } = await api.get('/api/services/active-deployments')
      return data.deployments || []
    },
    refetchInterval: 10000,
  })

  const { data: costs } = useQuery({
    queryKey: ['costs'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs')
      return data
    },
    enabled: canViewCosts,
    refetchInterval: 60000,
  })

  const { data: inventoryCounts } = useQuery({
    queryKey: ['inventory-counts', inventoryTypes.map((t) => t.slug)],
    queryFn: async () => {
      const counts: Record<string, number> = {}
      await Promise.all(
        inventoryTypes.map(async (t) => {
          try {
            const { data } = await api.get(`/api/inventory/${t.slug}?per_page=1`)
            counts[t.slug] = data.total ?? (data.objects?.length || 0)
          } catch {
            counts[t.slug] = 0
          }
        })
      )
      return counts
    },
    enabled: inventoryTypes.length > 0,
  })

  const { data: healthSummary } = useQuery({
    queryKey: ['health-summary'],
    queryFn: async () => {
      const { data } = await api.get('/api/health/summary')
      return data as HealthSummary
    },
    refetchInterval: 15000,
  })

  const runningJobs = jobs?.filter((j) => j.status === 'running') || []
  const completedJobs = jobs?.filter((j) => j.status === 'completed') || []
  const failedJobs = jobs?.filter((j) => j.status === 'failed') || []

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <StatCard title="Active Deployments" value={deployments?.length ?? '...'} icon={<Server className="h-4 w-4" />} loading={!deployments} />
      <StatCard title="Services" value={services?.length ?? '...'} icon={<Activity className="h-4 w-4" />} loading={!services} />
      {inventoryTypes.filter((t) => t.slug !== 'service').map((t) => (
        <StatCard key={t.slug} title={t.label} value={inventoryCounts?.[t.slug] ?? '...'} icon={<Database className="h-4 w-4" />} loading={!inventoryCounts} />
      ))}
      <StatCard title="Running Jobs" value={runningJobs.length} icon={<Play className="h-4 w-4" />} loading={jobsLoading} />
      <StatCard title="Completed Jobs" value={completedJobs.length} icon={<CheckCircle className="h-4 w-4" />} loading={jobsLoading} />
      <StatCard title="Failed Jobs" value={failedJobs.length} icon={<XCircle className="h-4 w-4" />} loading={jobsLoading} />
      <StatCard title="Service Health" value={healthSummary ? `${healthSummary.healthy}/${healthSummary.total}` : '...'} icon={<HeartPulse className="h-4 w-4" />} loading={!healthSummary} />
      {canViewCosts && (
        <StatCard title="Monthly Cost" value={costs?.total_monthly_cost != null ? `$${costs.total_monthly_cost.toFixed(2)}` : '...'} icon={<DollarSign className="h-4 w-4" />} loading={!costs} />
      )}
    </div>
  )
}

function StatCard({ title, value, icon, loading }: { title: string; value: string | number; icon: React.ReactNode; loading?: boolean }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            {loading ? <Skeleton className="h-7 w-16 mt-1" /> : <p className="text-2xl font-bold mt-1">{value}</p>}
          </div>
          <div className="text-muted-foreground">{icon}</div>
        </div>
      </CardContent>
    </Card>
  )
}
