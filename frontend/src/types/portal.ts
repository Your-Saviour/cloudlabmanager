export interface PortalService {
  name: string
  display_name: string
  power_status: string
  hostname: string
  ip: string
  fqdn: string | null
  region: string
  plan: string
  tags: string[]
  health: {
    overall_status: 'healthy' | 'unhealthy' | 'degraded' | 'unknown'
    checks: {
      name: string
      status: string
      response_time_ms: number | null
    }[]
  } | null
  outputs: {
    label: string
    type: string
    value: string
    username?: string
  }[]
  connection_guide: {
    ssh: string | null
    web_url: string | null
    fqdn: string | null
  }
  bookmarks: PortalBookmark[]
}

export interface PortalBookmark {
  id: number
  service_name: string
  label: string
  url: string | null
  notes: string | null
  sort_order: number
}

export interface PortalServicesResponse {
  services: PortalService[]
}
