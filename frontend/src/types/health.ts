export interface HealthCheck {
  check_name: string
  status: 'healthy' | 'unhealthy' | 'degraded' | 'unknown'
  check_type: 'http' | 'tcp' | 'icmp' | 'ssh_command'
  response_time_ms: number | null
  status_code: number | null
  error_message: string | null
  target: string | null
  checked_at: string | null
}

export interface ServiceHealth {
  service_name: string
  overall_status: 'healthy' | 'unhealthy' | 'degraded' | 'unknown'
  checks: HealthCheck[]
  interval: number
  notifications_enabled: boolean
}

export interface HealthStatusResponse {
  services: ServiceHealth[]
}

export interface HealthSummary {
  total: number
  healthy: number
  unhealthy: number
  unknown: number
}

export interface HealthHistoryResponse {
  service_name: string
  results: HealthCheck[]
}
