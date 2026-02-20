export interface User {
  id: number
  username: string
  display_name: string
  email: string
  is_active: boolean
  mfa_enabled?: boolean
  roles: Role[]
  permissions: string[]
  created_at: string
  last_login_at?: string
}

export interface Role {
  id: number
  name: string
  description: string
  permissions: Permission[]
}

export interface Permission {
  id: number
  codename: string
  description: string
  category: string
}

export interface InventoryType {
  slug: string
  label: string
  icon: string
  fields: InventoryField[]
  actions: InventoryAction[]
  sync?: { adapter: string }
}

export interface InventoryField {
  name: string
  type: 'string' | 'enum' | 'secret' | 'json' | 'text' | 'number' | 'boolean' | 'list'
  required?: boolean
  label?: string
  options?: string[]
  default?: unknown
  readonly?: boolean
}

export interface InventoryAction {
  name: string
  label: string
  scope: 'object' | 'type'
  type?: string
  confirm?: string
  permission?: string
  destructive?: boolean
}

export interface InventoryObject {
  id: number
  type_slug: string
  name: string
  data: Record<string, unknown>
  tags: Tag[]
  created_at: string
  updated_at: string
}

export interface Tag {
  id: number
  name: string
  color: string
  object_count?: number
}

export interface Job {
  id: string
  service: string
  action: string
  script?: string
  deployment_id?: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  output: string[]
  started_at: string
  finished_at?: string
  started_by?: string
  username?: string
  schedule_id?: number
  webhook_id?: number
  schedule_name?: string | null
  webhook_name?: string | null
  inputs?: Record<string, unknown>
  parent_job_id?: string
  object_id?: number
  type_slug?: string
}

export interface Service {
  name: string
  scripts: ServiceScript[]
  has_instance?: boolean
  configs?: string[]
}

export interface ServiceScript {
  name: string
  label: string
  inputs?: ScriptInput[]
}

export interface ScriptInput {
  name: string
  label: string
  type: string
  required?: boolean
  default?: string
  options?: string[]
}

export interface ServiceOutput {
  label: string
  type: string
  value: string
}

export interface AuditEntry {
  id: number
  user_id: number
  username: string
  action: string
  resource: string
  details: string
  timestamp: string
  ip_address?: string
}

export interface AuditFilters {
  usernames: string[]
  action_categories: string[]
  actions: string[]
}

export interface AuditListResponse {
  entries: AuditEntry[]
  total: number
  next_cursor: number | null
  per_page: number
}

export interface ACLEntry {
  id: number
  user_id: number
  username: string
  permission: string
}

export interface CostData {
  total_monthly_cost: number
  instances: CostInstance[]
  snapshot_storage?: {
    total_size_gb: number
    snapshot_count: number
    monthly_cost: number
  }
}

export interface CostInstance {
  label: string
  monthly_cost: number
  region: string
  plan: string
  tags: string[]
}

export interface InviteToken {
  id: number
  token: string
  email: string
  role_id: number
  created_at: string
  expires_at: string
  used: boolean
}

export interface TagPermission {
  id: number
  tag_id: number
  role_id: number
  role_name: string
  permission: string
}

export interface DryRunResult {
  service_name: string
  status: 'pass' | 'warn' | 'fail'
  cost_estimate: {
    total_monthly_cost: number
    currency: string
    plans_cache_available: boolean
    instances: DryRunInstance[]
  }
  dns_records: DryRunDnsRecord[]
  ssh_keys: {
    key_type: string
    key_name: string
    key_location: string
    note: string
  }
  validations: DryRunValidation[]
  permissions: {
    has_deploy_permission: boolean
    required_permissions: string[]
  }
}

export interface DryRunInstance {
  hostname: string
  plan: string
  region: string
  os: string
  monthly_cost: number
  hourly_cost: number
}

export interface DryRunDnsRecord {
  type: string
  record: string
  zone: string
  fqdn: string
  note: string
}

export interface DryRunValidation {
  check: string
  status: 'pass' | 'warn' | 'fail'
  message: string
}

export interface CostHistoryPoint {
  date: string
  total_monthly_cost: number
  instance_count: number
}

export interface CostHistoryResponse {
  data_points: CostHistoryPoint[]
  period: { from: string; to: string }
  granularity: string
}

export interface CostServicePoint {
  date: string
  services: Record<string, number>
  total: number
}

export interface CostSummary {
  current_total: number
  previous_total: number
  change_amount: number
  change_percent: number
  direction: 'up' | 'down' | 'flat'
  current_instance_count: number
  previous_instance_count: number
}

export interface ServiceACLEntry {
  id: number
  service_name: string
  role_id: number
  role_name: string | null
  permission: string
  created_at: string | null
  created_by: number | null
  created_by_username: string | null
}

export type ServicePermission = 'view' | 'deploy' | 'stop' | 'config'

export interface Snapshot {
  id: number
  vultr_snapshot_id: string
  instance_vultr_id: string | null
  instance_label: string | null
  description: string | null
  status: 'pending' | 'complete' | 'failed'
  size_gb: number | null
  os_id: number | null
  app_id: number | null
  vultr_created_at: string | null
  created_by_username: string | null
  created_at: string
  updated_at: string
}

export interface FileLibraryItem {
  id: number
  user_id: number
  username: string
  filename: string
  original_name: string
  size_bytes: number
  mime_type: string | null
  description: string | null
  tags: string[]
  uploaded_at: string
  last_used_at: string | null
}

export type { ScheduledJob, CronPreview } from './schedule'
export type { WebhookEndpoint } from './webhook'
