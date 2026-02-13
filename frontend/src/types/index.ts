export interface User {
  id: number
  username: string
  display_name: string
  email: string
  is_active: boolean
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

export interface ACLEntry {
  id: number
  user_id: number
  username: string
  permission: string
}

export interface CostData {
  total_monthly_cost: number
  instances: CostInstance[]
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
