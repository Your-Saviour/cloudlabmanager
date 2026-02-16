import { useNavigate } from 'react-router-dom'
import { Link2, Clock, DollarSign, Shield, User } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useHasPermission } from '@/lib/permissions'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'

export interface ServiceSummary {
  health_status?: 'healthy' | 'unhealthy' | 'degraded' | 'unknown'
  webhook_count?: number
  schedule_count?: number
  monthly_cost?: number
  acl_count?: number
  personal_enabled?: boolean
}

interface ServiceCrossLinksProps {
  serviceName: string
  summary?: ServiceSummary
}

const healthConfig: Record<string, { label: string; color: string; bgClass: string }> = {
  healthy:   { label: 'Healthy',   color: 'text-emerald-400', bgClass: 'bg-emerald-500' },
  degraded:  { label: 'Degraded',  color: 'text-amber-400',   bgClass: 'bg-amber-500' },
  unhealthy: { label: 'Unhealthy', color: 'text-red-400',     bgClass: 'bg-red-500' },
  unknown:   { label: 'Unknown',   color: 'text-zinc-400',    bgClass: 'bg-zinc-500' },
}

export function ServiceCrossLinks({ serviceName, summary }: ServiceCrossLinksProps) {
  const navigate = useNavigate()
  const canViewCosts = useHasPermission('costs.view')

  if (!summary) return null

  const { health_status, webhook_count, schedule_count, monthly_cost, acl_count, personal_enabled } = summary
  const hasAny = health_status || webhook_count || schedule_count || (canViewCosts && monthly_cost != null) || (acl_count != null && acl_count > 0) || personal_enabled
  if (!hasAny) return null

  const health = health_status ? healthConfig[health_status] || healthConfig.unknown : null

  return (
    <div className="flex gap-1.5 mt-2 flex-wrap">
      {/* Health status chip */}
      {health && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className="text-[11px] px-2 py-0.5 cursor-pointer hover:bg-accent/50 transition-colors gap-1.5"
              onClick={(e) => {
                e.stopPropagation()
                navigate(`/health?service=${encodeURIComponent(serviceName)}`)
              }}
              aria-label={`Health: ${health.label} — view checks for ${serviceName}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${health.bgClass}`} aria-hidden="true" />
              <span className={health.color}>{health.label}</span>
            </Badge>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            Health status — click to view checks
          </TooltipContent>
        </Tooltip>
      )}

      {/* Webhooks chip */}
      {webhook_count != null && webhook_count > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className="text-[11px] px-2 py-0.5 cursor-pointer hover:bg-accent/50 transition-colors gap-1.5"
              onClick={(e) => {
                e.stopPropagation()
                navigate(`/webhooks?service=${encodeURIComponent(serviceName)}`)
              }}
              aria-label={`${webhook_count} webhook${webhook_count !== 1 ? 's' : ''} — view for ${serviceName}`}
            >
              <Link2 className="h-3 w-3 text-blue-400" aria-hidden="true" />
              <span>{webhook_count} webhook{webhook_count !== 1 ? 's' : ''}</span>
            </Badge>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            Active webhooks — click to view
          </TooltipContent>
        </Tooltip>
      )}

      {/* Schedules chip */}
      {schedule_count != null && schedule_count > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className="text-[11px] px-2 py-0.5 cursor-pointer hover:bg-accent/50 transition-colors gap-1.5"
              onClick={(e) => {
                e.stopPropagation()
                navigate(`/schedules?service=${encodeURIComponent(serviceName)}`)
              }}
              aria-label={`${schedule_count} schedule${schedule_count !== 1 ? 's' : ''} — view for ${serviceName}`}
            >
              <Clock className="h-3 w-3 text-violet-400" aria-hidden="true" />
              <span>{schedule_count} schedule{schedule_count !== 1 ? 's' : ''}</span>
            </Badge>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            Active schedules — click to view
          </TooltipContent>
        </Tooltip>
      )}

      {/* Cost chip (permission-gated) */}
      {canViewCosts && monthly_cost != null && monthly_cost > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className="text-[11px] px-2 py-0.5 cursor-pointer hover:bg-accent/50 transition-colors gap-1.5"
              onClick={(e) => {
                e.stopPropagation()
                navigate('/costs')
              }}
              aria-label={`Monthly cost $${monthly_cost!.toFixed(2)} — view details`}
            >
              <DollarSign className="h-3 w-3 text-emerald-400" aria-hidden="true" />
              <span>${monthly_cost.toFixed(2)}/mo</span>
            </Badge>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            Monthly cost — click to view details
          </TooltipContent>
        </Tooltip>
      )}

      {/* ACL chip */}
      {acl_count != null && acl_count > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className="text-[11px] px-2 py-0.5 cursor-pointer hover:bg-accent/50 transition-colors gap-1.5"
              onClick={(e) => {
                e.stopPropagation()
                navigate(`/services/${encodeURIComponent(serviceName)}/config?tab=permissions`)
              }}
              aria-label={`Custom access controls configured — view permissions for ${serviceName}`}
            >
              <Shield className="h-3 w-3 text-orange-400" aria-hidden="true" />
              <span>ACL</span>
            </Badge>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            Custom access controls configured — click to view
          </TooltipContent>
        </Tooltip>
      )}

      {/* Personal instances chip */}
      {personal_enabled && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className="text-[11px] px-2 py-0.5 cursor-pointer hover:bg-accent/50 transition-colors gap-1.5"
              onClick={(e) => {
                e.stopPropagation()
                navigate(`/personal-instances?service=${encodeURIComponent(serviceName)}`)
              }}
              aria-label={`Personal instances enabled for ${serviceName}`}
            >
              <User className="h-3 w-3 text-cyan-400" aria-hidden="true" />
              <span>Personal</span>
            </Badge>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            Personal instances enabled — click to manage
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  )
}
