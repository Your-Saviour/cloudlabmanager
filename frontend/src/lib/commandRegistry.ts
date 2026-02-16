import { useQuery } from '@tanstack/react-query'

export function formatRelativeTime(timestamp: number): string {
  const seconds = Math.floor((Date.now() - timestamp) / 1000)
  if (seconds < 60) return 'Just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}
import { useInventoryStore } from '@/stores/inventoryStore'
import { useUIStore } from '@/stores/uiStore'
import { hasPermission } from '@/lib/permissions'
import api from '@/lib/api'
import type { InventoryObject, Service } from '@/types'

export interface CommandAction {
  id: string
  label: string
  sublabel?: string
  icon: string
  keywords?: string[]
  href?: string
  action?: () => void
  permission?: string
  category: 'system' | 'service' | 'inventory' | 'admin' | 'deploy' | 'run'
  // Fields for executable commands
  actionType?: 'deploy' | 'run_script'
  serviceName?: string
  script?: { name: string; label: string; inputs?: any[] }
  objId?: number
}

const STATIC_ACTIONS: CommandAction[] = [
  // System
  { id: 'refresh-costs', label: 'Refresh Costs', icon: 'DollarSign', href: '/costs', permission: 'costs.view', keywords: ['billing', 'update costs'], category: 'system' },
  { id: 'run-drift-check', label: 'Run Drift Check', icon: 'GitCompare', href: '/drift', permission: 'drift.view', keywords: ['compare', 'infrastructure diff'], category: 'system' },
  { id: 'reload-health', label: 'Reload Health Checks', icon: 'HeartPulse', href: '/health', permission: 'health.view', keywords: ['status', 'monitoring'], category: 'system' },
  { id: 'export-audit', label: 'Export Audit Log', icon: 'ScrollText', href: '/audit', permission: 'system.audit_log', keywords: ['download', 'csv', 'json'], category: 'system' },
  { id: 'stop-all', label: 'Stop All Services', icon: 'OctagonX', href: '/services', permission: 'system.stop_all', keywords: ['shutdown', 'kill'], category: 'system' },
  // Admin
  { id: 'create-webhook', label: 'Create Webhook', icon: 'Webhook', href: '/webhooks', permission: 'webhooks.create', keywords: ['hook', 'trigger', 'new'], category: 'admin' },
  { id: 'create-schedule', label: 'Create Schedule', icon: 'Clock', href: '/schedules', permission: 'schedules.create', keywords: ['cron', 'timer', 'new'], category: 'admin' },
  { id: 'invite-user', label: 'Invite User', icon: 'UserPlus', href: '/users', permission: 'users.create', keywords: ['new user', 'add user'], category: 'admin' },
  // Feedback
  { id: 'report-bug', label: 'Report Bug', icon: 'Bug', keywords: ['bug', 'report', 'issue', 'feedback'], permission: 'bug_reports.submit', action: () => useUIStore.getState().setReportBugOpen(true), category: 'system' },
]

export function useCommandActions() {
  const types = useInventoryStore((s) => s.types)

  const { data: serviceObjects = [] } = useQuery({
    queryKey: ['inventory', 'service'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/service')
      return (data.objects || []) as InventoryObject[]
    },
    staleTime: 30_000,
  })

  const { data: servicesData = [] } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const { data } = await api.get('/api/services')
      return (data.services || []) as Service[]
    },
    staleTime: 30_000,
  })

  const staticActions = STATIC_ACTIONS.filter(
    (action) => !action.permission || hasPermission(action.permission)
  )

  const serviceCommands: CommandAction[] = serviceObjects.map((obj) => {
    const name = (obj.data.name as string) || obj.name
    const isRunning = obj.data.power_status === 'running'
    return {
      id: `service:${name}`,
      label: name,
      sublabel: isRunning ? 'Running' : 'Stopped',
      icon: 'Boxes',
      keywords: [name, 'service'],
      href: '/services',
      permission: 'services.view',
      category: 'service' as const,
    }
  })

  const inventoryCommands: CommandAction[] = types.map((t) => ({
    id: `inventory:${t.slug}`,
    label: t.label,
    icon: 'Server',
    keywords: [t.slug, 'inventory'],
    href: `/inventory/${t.slug}`,
    category: 'inventory' as const,
  }))

  const deployCommands: CommandAction[] = []
  for (const svc of servicesData) {
    const deployScript = svc.scripts.find((s) => s.name === 'deploy')
    if (!deployScript) continue

    const obj = serviceObjects.find(
      (o) => (o.data.name as string) === svc.name || o.name === svc.name
    )

    deployCommands.push({
      id: `deploy:${svc.name}`,
      label: `Deploy ${svc.name}`,
      icon: 'Rocket',
      keywords: [svc.name, 'deploy', 'start', 'launch'],
      permission: 'services.deploy',
      category: 'deploy',
      actionType: 'deploy',
      serviceName: svc.name,
      script: deployScript,
      objId: obj?.id,
    })
  }

  const runCommands: CommandAction[] = []
  for (const svc of servicesData) {
    const obj = serviceObjects.find(
      (o) => (o.data.name as string) === svc.name || o.name === svc.name
    )

    for (const script of svc.scripts) {
      if (script.name === 'deploy') continue

      runCommands.push({
        id: `run:${svc.name}:${script.name}`,
        label: `Run ${svc.name}: ${script.label}`,
        icon: 'PlayCircle',
        keywords: [svc.name, script.name, script.label, 'run', 'script', 'execute'],
        permission: 'services.deploy',
        category: 'run',
        actionType: 'run_script',
        serviceName: svc.name,
        script,
        objId: obj?.id,
      })
    }
  }

  return {
    actions: staticActions,
    services: serviceCommands,
    inventory: inventoryCommands,
    deployCommands,
    runCommands,
  }
}
