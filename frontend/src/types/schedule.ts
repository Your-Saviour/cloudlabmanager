export interface ScheduledJob {
  id: number
  name: string
  description: string | null
  job_type: 'service_script' | 'inventory_action' | 'system_task'
  service_name: string | null
  script_name: string | null
  type_slug: string | null
  action_name: string | null
  object_id: number | null
  system_task: string | null
  cron_expression: string
  is_enabled: boolean
  inputs: Record<string, unknown> | null
  skip_if_running: boolean
  last_run_at: string | null
  last_job_id: string | null
  last_status: string | null
  next_run_at: string | null
  created_by: number | null
  created_by_username: string | null
  created_at: string
  updated_at: string
}

export interface CronPreview {
  expression: string
  next_runs: string[]
}
