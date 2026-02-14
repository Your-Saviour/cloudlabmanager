import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { HeartPulse, RefreshCw, ChevronDown, ChevronRight, AlertCircle, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/lib/api'
import { cn, relativeTime } from '@/lib/utils'
import { useHasPermission } from '@/lib/permissions'
import { PageHeader } from '@/components/shared/PageHeader'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { HealthStatusResponse, ServiceHealth, HealthCheck } from '@/types/health'

export default function HealthPage() {
  const canManage = useHasPermission('health.manage')
  const [reloading, setReloading] = useState(false)
  const [rechecking, setRechecking] = useState(false)

  const { data: healthStatus, isLoading, refetch } = useQuery({
    queryKey: ['health-status'],
    queryFn: async () => {
      const { data } = await api.get('/api/health/status')
      return data as HealthStatusResponse
    },
    refetchInterval: 15000,
  })

  const services = healthStatus?.services || []
  const healthy = services.filter((s) => s.overall_status === 'healthy').length
  const unhealthy = services.filter((s) => s.overall_status === 'unhealthy').length
  const degraded = services.filter((s) => s.overall_status === 'degraded').length
  const unknown = services.filter((s) => s.overall_status === 'unknown').length

  const handleReload = async () => {
    setReloading(true)
    try {
      await api.post('/api/health/reload')
      refetch()
      toast.success('Health configs reloaded')
    } catch {
      toast.error('Failed to reload health configs')
    } finally {
      setReloading(false)
    }
  }

  const handleRecheck = async () => {
    setRechecking(true)
    try {
      await api.post('/api/health/recheck')
      refetch()
      toast.success('Health checks completed')
    } catch {
      toast.error('Failed to run health checks')
    } finally {
      setRechecking(false)
    }
  }

  return (
    <div>
      <PageHeader title="Service Health" description="Live health monitoring for deployed services">
        {canManage && (
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleRecheck} disabled={rechecking}>
              {rechecking
                ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                : <RefreshCw className="mr-2 h-3.5 w-3.5" />}
              Recheck Now
            </Button>
            <Button variant="outline" size="sm" onClick={handleReload} disabled={reloading}>
              {reloading
                ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                : <RefreshCw className="mr-2 h-3.5 w-3.5" />}
              Reload Configs
            </Button>
          </div>
        )}
      </PageHeader>

      {/* Summary bar */}
      <div className="flex flex-wrap gap-3 mb-6">
        <Badge variant="outline" className="text-green-500 border-green-500/30">
          <span aria-hidden="true" className="mr-1.5 inline-block h-2 w-2 rounded-full bg-green-500" />
          {healthy} Healthy
        </Badge>
        {unhealthy > 0 && (
          <Badge variant="outline" className="text-red-500 border-red-500/30">
            <span aria-hidden="true" className="mr-1.5 inline-block h-2 w-2 rounded-full bg-red-500 animate-pulse" />
            {unhealthy} Unhealthy
          </Badge>
        )}
        {degraded > 0 && (
          <Badge variant="outline" className="text-yellow-500 border-yellow-500/30">
            <span aria-hidden="true" className="mr-1.5 inline-block h-2 w-2 rounded-full bg-yellow-500" />
            {degraded} Degraded
          </Badge>
        )}
        <Badge variant="outline" className="text-gray-500 border-gray-500/30">
          <span aria-hidden="true" className="mr-1.5 inline-block h-2 w-2 rounded-full bg-gray-500" />
          {unknown} Unknown
        </Badge>
      </div>

      {/* Service health cards */}
      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : services.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <HeartPulse className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">No health checks configured</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {services.map((svc) => (
            <ServiceHealthCard key={svc.service_name} service={svc} />
          ))}
        </div>
      )}
    </div>
  )
}

function ServiceHealthCard({ service }: { service: ServiceHealth }) {
  const [expanded, setExpanded] = useState(false)

  const avgResponseTime = (() => {
    const times = service.checks
      .map((c) => c.response_time_ms)
      .filter((t): t is number => t != null)
    if (times.length === 0) return null
    return Math.round(times.reduce((a, b) => a + b, 0) / times.length)
  })()

  const lastChecked = service.checks[0]?.checked_at

  return (
    <Card className={cn(
      "transition-colors",
      service.overall_status === 'unhealthy' && "border-destructive/50",
      service.overall_status === 'healthy' && "border-green-500/20",
      service.overall_status === 'degraded' && "border-yellow-500/20",
    )}>
      <button
        className="w-full text-left px-6 py-4"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-label={`${service.service_name} — ${service.overall_status}`}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {expanded
              ? <ChevronDown className="h-4 w-4 text-muted-foreground" />
              : <ChevronRight className="h-4 w-4 text-muted-foreground" />
            }
            <HealthDot status={service.overall_status} />
            <span className="font-medium">{service.service_name}</span>
            <StatusLabel status={service.overall_status} />
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            {avgResponseTime != null && (
              <span>{avgResponseTime}ms avg</span>
            )}
            {lastChecked && (
              <span>{relativeTime(lastChecked)}</span>
            )}
            <span>{service.checks.length} check{service.checks.length !== 1 ? 's' : ''}</span>
          </div>
        </div>
      </button>

      {expanded && (
        <CardContent className="pt-0 pb-4">
          <div className="border-t pt-4">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground border-b">
                    <th scope="col" className="pb-2 pr-4 font-medium">Check Name</th>
                    <th scope="col" className="pb-2 pr-4 font-medium">Type</th>
                    <th scope="col" className="pb-2 pr-4 font-medium">Target</th>
                    <th scope="col" className="pb-2 pr-4 font-medium">Status</th>
                    <th scope="col" className="pb-2 pr-4 font-medium">Response Time</th>
                    <th scope="col" className="pb-2 pr-4 font-medium">Last Checked</th>
                    <th scope="col" className="pb-2 font-medium">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {service.checks.map((check, i) => (
                    <CheckRow key={i} check={check} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </CardContent>
      )}
    </Card>
  )
}

function CheckRow({ check }: { check: HealthCheck }) {
  return (
    <tr className="border-b last:border-0">
      <td className="py-2 pr-4 font-medium">{check.check_name}</td>
      <td className="py-2 pr-4">
        <Badge variant="secondary" className="text-xs">{check.check_type}</Badge>
      </td>
      <td className="py-2 pr-4 text-muted-foreground text-xs font-mono max-w-[200px] truncate">
        {check.target || '—'}
      </td>
      <td className="py-2 pr-4">
        <div className="flex items-center gap-1.5">
          <HealthDot status={check.status} />
          <span className="text-xs">{check.status}</span>
        </div>
      </td>
      <td className="py-2 pr-4 text-muted-foreground">
        {check.response_time_ms != null ? `${check.response_time_ms}ms` : '—'}
      </td>
      <td className="py-2 pr-4 text-muted-foreground text-xs">
        {check.checked_at ? relativeTime(check.checked_at) : '—'}
      </td>
      <td className="py-2">
        {check.error_message ? (
          <div className="flex items-center gap-1.5 text-destructive text-xs max-w-[250px]">
            <AlertCircle className="h-3 w-3 shrink-0" />
            <span className="truncate" title={check.error_message}>{check.error_message}</span>
          </div>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
    </tr>
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
        "inline-block h-2.5 w-2.5 rounded-full shrink-0",
        colors[status as keyof typeof colors] || colors.unknown,
        status === 'unhealthy' && "animate-pulse",
      )}
      role="img"
      aria-label={status}
    />
  )
}

function StatusLabel({ status }: { status: string }) {
  const styles = {
    healthy: 'text-green-500',
    unhealthy: 'text-red-500',
    degraded: 'text-yellow-500',
    unknown: 'text-gray-500',
  }
  return (
    <span className={cn(
      "text-xs font-medium capitalize",
      styles[status as keyof typeof styles] || styles.unknown,
    )}>
      {status}
    </span>
  )
}
