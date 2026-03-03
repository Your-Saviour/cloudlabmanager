import type { WidgetType } from '@/types/preferences'
import { PinnedServicesWidget } from './PinnedServicesWidget'
import { StatsWidget } from './StatsWidget'
import { QuickLinksWidget } from './QuickLinksWidget'
import { HealthWidget } from './HealthWidget'
import { RecentJobsWidget } from './RecentJobsWidget'
import { ServiceToggleWidget } from './ServiceToggleWidget'
import { ScriptRunnerWidget } from './ScriptRunnerWidget'

export interface WidgetMeta {
  type: WidgetType
  label: string
  description: string
  component: React.ComponentType<{ config: Record<string, any> }>
  defaultSize: { w: number; h: number; minW: number; minH: number }
  singleton: boolean
  requiredPermission?: string
  configurable?: boolean
}

export const WIDGET_REGISTRY: Record<WidgetType, WidgetMeta> = {
  pinned_services: {
    type: 'pinned_services',
    label: 'Pinned Services',
    description: 'Your pinned service cards with deploy/stop actions',
    component: PinnedServicesWidget,
    defaultSize: { w: 12, h: 4, minW: 6, minH: 2 },
    singleton: true,
  },
  stats: {
    type: 'stats',
    label: 'Statistics',
    description: 'Active deployments, job counts, health, and cost overview',
    component: StatsWidget,
    defaultSize: { w: 12, h: 3, minW: 6, minH: 2 },
    singleton: true,
  },
  quick_links: {
    type: 'quick_links',
    label: 'Quick Links',
    description: 'Auto-discovered service URLs and custom links',
    component: QuickLinksWidget,
    defaultSize: { w: 12, h: 4, minW: 4, minH: 2 },
    singleton: true,
  },
  health: {
    type: 'health',
    label: 'Service Health',
    description: 'Health status cards for monitored services',
    component: HealthWidget,
    defaultSize: { w: 6, h: 4, minW: 4, minH: 3 },
    singleton: true,
  },
  recent_jobs: {
    type: 'recent_jobs',
    label: 'Recent Jobs',
    description: 'Last 5 jobs with status and timing',
    component: RecentJobsWidget,
    defaultSize: { w: 6, h: 4, minW: 4, minH: 3 },
    singleton: true,
  },
  service_toggle: {
    type: 'service_toggle',
    label: 'Service Toggle',
    description: 'Deploy/Stop toggle button for a single service',
    component: ServiceToggleWidget,
    defaultSize: { w: 3, h: 2, minW: 2, minH: 2 },
    singleton: false,
    requiredPermission: 'services.deploy',
    configurable: true,
  },
  script_runner: {
    type: 'script_runner',
    label: 'Script Runner',
    description: 'Run a script from the file library on a service',
    component: ScriptRunnerWidget,
    defaultSize: { w: 4, h: 3, minW: 3, minH: 2 },
    singleton: false,
    requiredPermission: 'files.view',
    configurable: true,
  },
}
