export interface Vpc {
  id: string
  region: string
  description: string
  v4_subnet: string
  v4_subnet_mask: number
  date_created?: string
}

export interface VpcAttachment {
  id: string
  description: string
  ip_address?: string
}

export interface VpcInstance {
  label: string
  hostname: string
  main_ip: string
  region: string
  firewall_group_id?: string | null
  attached_vpcs: VpcAttachment[]
}

export interface FirewallRule {
  id: number
  ip_type: string
  protocol: string
  port: string
  subnet: string
  subnet_size: number
  source: string
  notes: string
}

export interface FirewallGroup {
  id: string
  description: string
  rules: FirewallRule[]
}

export interface VpcReport {
  vpcs: Vpc[]
  instances: Record<string, VpcInstance>
  firewall_groups: FirewallGroup[]
}

export interface VpcReportResponse extends VpcReport {
  last_synced: string | null
}
