export type WidgetType = 'pinned_services' | 'stats' | 'quick_links' | 'health' | 'recent_jobs' | 'service_toggle' | 'script_runner'

export interface WidgetInstance {
  id: string
  type: WidgetType
  title?: string
  config: Record<string, any>
}

export interface WidgetLayoutItem {
  i: string; x: number; y: number; w: number; h: number
  minW?: number; minH?: number
}

export interface WidgetDashboard {
  version: 1
  widgets: WidgetInstance[]
  layouts: { lg: WidgetLayoutItem[] }
}

export const DEFAULT_WIDGET_DASHBOARD: WidgetDashboard = {
  version: 1,
  widgets: [
    { id: 'pinned_services_default', type: 'pinned_services', config: {} },
    { id: 'stats_default', type: 'stats', config: {} },
    { id: 'quick_links_default', type: 'quick_links', config: {} },
    { id: 'health_default', type: 'health', config: {} },
    { id: 'recent_jobs_default', type: 'recent_jobs', config: {} },
  ],
  layouts: {
    lg: [
      { i: 'pinned_services_default', x: 0, y: 0, w: 12, h: 4, minW: 6, minH: 2 },
      { i: 'stats_default', x: 0, y: 4, w: 12, h: 3, minW: 6, minH: 2 },
      { i: 'quick_links_default', x: 0, y: 7, w: 12, h: 4, minW: 4, minH: 2 },
      { i: 'health_default', x: 0, y: 11, w: 6, h: 4, minW: 4, minH: 3 },
      { i: 'recent_jobs_default', x: 6, y: 11, w: 6, h: 4, minW: 4, minH: 3 },
    ],
  },
}

export interface DashboardSectionConfig {
  order: string[]
  collapsed: string[]
}

export interface CustomLink {
  id: string       // UUID or timestamp-based unique ID
  label: string
  url: string
  icon?: string    // Optional: emoji or icon name
}

export interface QuickLinksConfig {
  order: string[]      // e.g. ["n8n-server:Admin Console", "velociraptor:Web UI"]
  hidden: string[]
  custom_links: CustomLink[]
}

export interface UserPreferences {
  pinned_services: string[]
  dashboard_sections: DashboardSectionConfig
  quick_links: QuickLinksConfig
  widget_dashboard?: WidgetDashboard
}

export const DEFAULT_PREFERENCES: UserPreferences = {
  pinned_services: [],
  dashboard_sections: {
    order: ['pinned_services', 'stats', 'quick_links', 'health', 'recent_jobs'],
    collapsed: [],
  },
  quick_links: {
    order: [],
    hidden: [],
    custom_links: [],
  },
}
