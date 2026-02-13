import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Server, Play, Activity, DollarSign, ArrowRight, Clock, ExternalLink, CheckCircle, XCircle, Database, HeartPulse } from 'lucide-react'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import { useHasPermission } from '@/lib/permissions'
import { useInventoryStore } from '@/stores/inventoryStore'
import { relativeTime } from '@/lib/utils'
import { PageHeader } from '@/components/shared/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Skeleton } from '@/components/ui/skeleton'
import type { Job, Service } from '@/types'
import type { HealthSummary, HealthStatusResponse } from '@/types/health'

export default function DashboardPage() {
  const navigate = useNavigate()
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

  // Service outputs for quick links
  const { data: serviceOutputs } = useQuery({
    queryKey: ['service-outputs'],
    queryFn: async () => {
      const { data } = await api.get('/api/services/outputs')
      return data.outputs as Record<string, { label: string; type: string; value: string }[]>
    },
    refetchInterval: 30000,
  })

  // Inventory type counts
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

  const { data: healthStatus } = useQuery({
    queryKey: ['health-status'],
    queryFn: async () => {
      const { data } = await api.get('/api/health/status')
      return data as HealthStatusResponse
    },
    refetchInterval: 15000,
  })

  const runningJobs = jobs?.filter((j) => j.status === 'running') || []
  const completedJobs = jobs?.filter((j) => j.status === 'completed') || []
  const failedJobs = jobs?.filter((j) => j.status === 'failed') || []
  const recentJobs = jobs?.slice(0, 5) || []

  // Collect quick links from service outputs
  const quickLinks: { service: string; label: string; url: string }[] = []
  if (serviceOutputs) {
    for (const [service, outputs] of Object.entries(serviceOutputs)) {
      for (const out of outputs) {
        if (out.type === 'url' && out.value) {
          quickLinks.push({ service, label: out.label, url: out.value })
        }
      }
    }
  }

  return (
    <div>
      <PageHeader title="Dashboard" description="Overview of your CloudLab environment" />

      {/* Stat Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-8">
        <StatCard
          title="Active Deployments"
          value={deployments?.length ?? '...'}
          icon={<Server className="h-4 w-4" />}
          loading={!deployments}
        />
        <StatCard
          title="Services"
          value={services?.length ?? '...'}
          icon={<Activity className="h-4 w-4" />}
          loading={!services}
        />

        {/* Inventory type counts */}
        {inventoryTypes
          .filter((t) => t.slug !== 'service')
          .map((t) => (
            <StatCard
              key={t.slug}
              title={t.label}
              value={inventoryCounts?.[t.slug] ?? '...'}
              icon={<Database className="h-4 w-4" />}
              loading={!inventoryCounts}
            />
          ))}

        {/* Job breakdown */}
        <StatCard
          title="Running Jobs"
          value={runningJobs.length}
          icon={<Play className="h-4 w-4" />}
          loading={jobsLoading}
        />
        <StatCard
          title="Completed Jobs"
          value={completedJobs.length}
          icon={<CheckCircle className="h-4 w-4" />}
          loading={jobsLoading}
        />
        <StatCard
          title="Failed Jobs"
          value={failedJobs.length}
          icon={<XCircle className="h-4 w-4" />}
          loading={jobsLoading}
        />
        <StatCard
          title="Service Health"
          value={healthSummary
            ? `${healthSummary.healthy}/${healthSummary.total}`
            : '...'}
          icon={<HeartPulse className="h-4 w-4" />}
          loading={!healthSummary}
        />

        {canViewCosts && (
          <StatCard
            title="Monthly Cost"
            value={costs?.total_monthly_cost != null ? `$${costs.total_monthly_cost.toFixed(2)}` : '...'}
            icon={<DollarSign className="h-4 w-4" />}
            loading={!costs}
          />
        )}
      </div>

      {/* Quick Links */}
      {quickLinks.length > 0 && (
        <div className="mb-8">
          <h2 className="text-base font-semibold mb-3">Quick Links</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {quickLinks.map((link, i) => (
              <a
                key={i}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group block"
              >
                <Card className="transition-colors hover:border-primary/50">
                  <CardContent className="pt-4 pb-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium group-hover:text-primary transition-colors">
                          {link.label}
                        </p>
                        <p className="text-xs text-muted-foreground">{link.service}</p>
                      </div>
                      <ExternalLink className="h-3.5 w-3.5 text-muted-foreground group-hover:text-primary transition-colors" />
                    </div>
                  </CardContent>
                </Card>
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Health Status Panel */}
      {healthStatus?.services && healthStatus.services.length > 0 && (
        <div className="mb-8">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-base font-semibold">Service Health</h2>
            <Button variant="ghost" size="sm" onClick={() => navigate('/health')}>
              View All <ArrowRight className="ml-1 h-3 w-3" />
            </Button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {healthStatus.services.map((svc) => (
              <Card
                key={svc.service_name}
                role="button"
                tabIndex={0}
                aria-label={`${svc.service_name} — ${svc.overall_status}`}
                className={cn(
                  "cursor-pointer transition-colors hover:border-primary/50",
                  svc.overall_status === 'unhealthy' && "border-destructive/50",
                  svc.overall_status === 'healthy' && "border-green-500/30",
                )}
                onClick={() => navigate('/health')}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') navigate('/health') }}
              >
                <CardContent className="pt-4 pb-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <HealthDot status={svc.overall_status} />
                      <span className="font-medium text-sm">{svc.service_name}</span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {svc.checks[0]?.response_time_ms != null
                        ? `${svc.checks[0].response_time_ms}ms`
                        : '—'}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Recent Jobs */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">Recent Jobs</CardTitle>
          <Button variant="ghost" size="sm" onClick={() => navigate('/jobs')}>
            View All <ArrowRight className="ml-1 h-3 w-3" />
          </Button>
        </CardHeader>
        <CardContent>
          {jobsLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : recentJobs.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-6">No jobs yet</p>
          ) : (
            <div className="space-y-2">
              {recentJobs.map((job) => (
                <button
                  key={job.id}
                  className="flex items-center justify-between w-full rounded-md px-3 py-2 text-sm hover:bg-muted/50 transition-colors text-left"
                  onClick={() => navigate(`/jobs/${job.id}`)}
                >
                  <div className="flex items-center gap-3">
                    <StatusBadge status={job.status} />
                    <span className="font-medium">{job.service}</span>
                    <span className="text-muted-foreground">{job.action}</span>
                  </div>
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    <span className="text-xs">{relativeTime(job.started_at)}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function HealthDot({ status }: { status: string }) {
  const colors = {
    healthy: 'bg-green-500',
    unhealthy: 'bg-red-500',
    degraded: 'bg-yellow-500',
    unknown: 'bg-gray-500',
  }
  return (
    <span
      className={cn(
        "inline-block h-2.5 w-2.5 rounded-full",
        colors[status as keyof typeof colors] || colors.unknown,
        status === 'unhealthy' && "animate-pulse",
      )}
      role="img"
      aria-label={status}
    />
  )
}

function StatCard({
  title,
  value,
  icon,
  loading,
}: {
  title: string
  value: string | number
  icon: React.ReactNode
  loading?: boolean
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            {loading ? (
              <Skeleton className="h-7 w-16 mt-1" />
            ) : (
              <p className="text-2xl font-bold mt-1">{value}</p>
            )}
          </div>
          <div className="text-muted-foreground">{icon}</div>
        </div>
      </CardContent>
    </Card>
  )
}
