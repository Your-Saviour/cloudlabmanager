export interface WebhookEndpoint {
  id: number
  name: string
  description: string | null
  token?: string
  job_type: 'service_script' | 'inventory_action' | 'system_task'
  service_name: string | null
  script_name: string | null
  type_slug: string | null
  action_name: string | null
  object_id: number | null
  system_task: string | null
  payload_mapping: Record<string, string> | null
  is_enabled: boolean
  last_trigger_at: string | null
  last_job_id: string | null
  last_status: string | null
  trigger_count: number
  created_by: number | null
  created_by_username: string | null
  created_at: string
  updated_at: string
}
