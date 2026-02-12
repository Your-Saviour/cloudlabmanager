import { Badge } from '@/components/ui/badge'

const statusVariantMap: Record<string, 'success' | 'destructive' | 'running' | 'warning' | 'secondary'> = {
  running: 'running',
  completed: 'success',
  failed: 'destructive',
  cancelled: 'secondary',
  pending: 'warning',
  stopped: 'secondary',
}

interface StatusBadgeProps {
  status: string
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const variant = statusVariantMap[status] || 'secondary'
  return <Badge variant={variant}>{status}</Badge>
}
