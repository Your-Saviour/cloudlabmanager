import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import { Card, CardContent } from '@/components/ui/card'
import type { HealthStatusResponse } from '@/types/health'

export function HealthWidget(_props: { config: Record<string, any> }) {
  const navigate = useNavigate()

  const { data: healthStatus } = useQuery({
    queryKey: ['health-status'],
    queryFn: async () => {
      const { data } = await api.get('/api/health/status')
      return data as HealthStatusResponse
    },
    refetchInterval: 15000,
  })

  if (!healthStatus?.services || healthStatus.services.length === 0) {
    return <p className="text-sm text-muted-foreground text-center py-4">No health checks configured.</p>
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
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
                {svc.checks[0]?.response_time_ms != null ? `${svc.checks[0].response_time_ms}ms` : '—'}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function HealthDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    healthy: 'bg-green-500',
    unhealthy: 'bg-red-500',
    degraded: 'bg-yellow-500',
    unknown: 'bg-gray-500',
  }
  return (
    <span
      className={cn(
        "inline-block h-2.5 w-2.5 rounded-full",
        colors[status] || colors.unknown,
        status === 'unhealthy' && "animate-pulse",
      )}
      role="img"
      aria-label={status}
    />
  )
}
