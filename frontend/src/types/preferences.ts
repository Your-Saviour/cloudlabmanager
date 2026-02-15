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
