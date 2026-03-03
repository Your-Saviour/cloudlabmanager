import { create } from 'zustand'
import api from '@/lib/api'
import type { UserPreferences, CustomLink, WidgetDashboard, WidgetInstance, WidgetLayoutItem } from '@/types/preferences'
import { DEFAULT_PREFERENCES, DEFAULT_WIDGET_DASHBOARD } from '@/types/preferences'

interface PreferencesState {
  preferences: UserPreferences
  loaded: boolean

  // Actions
  loadPreferences: () => Promise<void>
  togglePinService: (serviceName: string) => void
  isServicePinned: (serviceName: string) => boolean
  toggleSectionCollapsed: (sectionId: string) => void
  isSectionCollapsed: (sectionId: string) => boolean
  reorderSections: (newOrder: string[]) => void
  reorderQuickLinks: (newOrder: string[]) => void
  addCustomLink: (link: CustomLink) => void
  removeCustomLink: (linkId: string) => void
  editCustomLink: (linkId: string, updates: Partial<CustomLink>) => void

  // Widget dashboard actions
  getWidgetDashboard: () => WidgetDashboard
  updateWidgetLayouts: (layouts: { lg: WidgetLayoutItem[] }) => void
  addWidget: (widget: WidgetInstance, layout: WidgetLayoutItem) => void
  removeWidget: (widgetId: string) => void
  updateWidgetConfig: (widgetId: string, config: Record<string, any>) => void
  updateWidgetTitle: (widgetId: string, title: string) => void
}

let saveTimeout: ReturnType<typeof setTimeout> | null = null

function debouncedSave(preferences: UserPreferences) {
  if (saveTimeout) clearTimeout(saveTimeout)
  saveTimeout = setTimeout(async () => {
    try {
      await api.put('/api/users/me/preferences', preferences)
    } catch (e) {
      console.error('Failed to save preferences:', e)
    }
  }, 300)
}

export const usePreferencesStore = create<PreferencesState>()((set, get) => ({
  preferences: DEFAULT_PREFERENCES,
  loaded: false,

  loadPreferences: async () => {
    try {
      const { data } = await api.get('/api/users/me/preferences')
      const merged = { ...DEFAULT_PREFERENCES, ...data.preferences }
      // Ensure nested objects have defaults
      merged.dashboard_sections = { ...DEFAULT_PREFERENCES.dashboard_sections, ...merged.dashboard_sections }
      merged.quick_links = { ...DEFAULT_PREFERENCES.quick_links, ...merged.quick_links }
      if (!Array.isArray(merged.quick_links.custom_links)) {
        merged.quick_links.custom_links = []
      }

      // Migrate: if no widget_dashboard, generate default and save
      if (!merged.widget_dashboard) {
        merged.widget_dashboard = { ...DEFAULT_WIDGET_DASHBOARD }
        set({ preferences: merged, loaded: true })
        debouncedSave(merged)
      } else {
        set({ preferences: merged, loaded: true })
      }
    } catch {
      set({ loaded: true })
    }
  },

  togglePinService: (serviceName: string) => {
    const { preferences } = get()
    const pinned = preferences.pinned_services.includes(serviceName)
      ? preferences.pinned_services.filter((s) => s !== serviceName)
      : [...preferences.pinned_services, serviceName]
    const updated = { ...preferences, pinned_services: pinned }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  isServicePinned: (serviceName: string) => {
    return get().preferences.pinned_services.includes(serviceName)
  },

  toggleSectionCollapsed: (sectionId: string) => {
    const { preferences } = get()
    const collapsed = preferences.dashboard_sections.collapsed.includes(sectionId)
      ? preferences.dashboard_sections.collapsed.filter((s) => s !== sectionId)
      : [...preferences.dashboard_sections.collapsed, sectionId]
    const updated = {
      ...preferences,
      dashboard_sections: { ...preferences.dashboard_sections, collapsed },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  isSectionCollapsed: (sectionId: string) => {
    return get().preferences.dashboard_sections.collapsed.includes(sectionId)
  },

  reorderSections: (newOrder: string[]) => {
    const { preferences } = get()
    const updated = {
      ...preferences,
      dashboard_sections: { ...preferences.dashboard_sections, order: newOrder },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  reorderQuickLinks: (newOrder: string[]) => {
    const { preferences } = get()
    const updated = {
      ...preferences,
      quick_links: { ...preferences.quick_links, order: newOrder },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  addCustomLink: (link: CustomLink) => {
    const { preferences } = get()
    const customId = `custom:${link.id}`
    const updated = {
      ...preferences,
      quick_links: {
        ...preferences.quick_links,
        custom_links: [...preferences.quick_links.custom_links, link],
        order: [...preferences.quick_links.order, customId],
      },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  removeCustomLink: (linkId: string) => {
    const { preferences } = get()
    const customId = `custom:${linkId}`
    const updated = {
      ...preferences,
      quick_links: {
        ...preferences.quick_links,
        custom_links: preferences.quick_links.custom_links.filter((l) => l.id !== linkId),
        order: preferences.quick_links.order.filter((id) => id !== customId),
      },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  editCustomLink: (linkId: string, updates: Partial<CustomLink>) => {
    const { preferences } = get()
    const updated = {
      ...preferences,
      quick_links: {
        ...preferences.quick_links,
        custom_links: preferences.quick_links.custom_links.map((l) =>
          l.id === linkId ? { ...l, ...updates } : l
        ),
      },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  // Widget dashboard actions
  getWidgetDashboard: () => {
    return get().preferences.widget_dashboard ?? DEFAULT_WIDGET_DASHBOARD
  },

  updateWidgetLayouts: (layouts: { lg: WidgetLayoutItem[] }) => {
    const { preferences } = get()
    const dashboard = preferences.widget_dashboard ?? DEFAULT_WIDGET_DASHBOARD
    const updated = {
      ...preferences,
      widget_dashboard: { ...dashboard, layouts },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  addWidget: (widget: WidgetInstance, layout: WidgetLayoutItem) => {
    const { preferences } = get()
    const dashboard = preferences.widget_dashboard ?? DEFAULT_WIDGET_DASHBOARD
    const updated = {
      ...preferences,
      widget_dashboard: {
        ...dashboard,
        widgets: [...dashboard.widgets, widget],
        layouts: {
          lg: [...dashboard.layouts.lg, layout],
        },
      },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  removeWidget: (widgetId: string) => {
    const { preferences } = get()
    const dashboard = preferences.widget_dashboard ?? DEFAULT_WIDGET_DASHBOARD
    const updated = {
      ...preferences,
      widget_dashboard: {
        ...dashboard,
        widgets: dashboard.widgets.filter((w) => w.id !== widgetId),
        layouts: {
          lg: dashboard.layouts.lg.filter((l) => l.i !== widgetId),
        },
      },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  updateWidgetConfig: (widgetId: string, config: Record<string, any>) => {
    const { preferences } = get()
    const dashboard = preferences.widget_dashboard ?? DEFAULT_WIDGET_DASHBOARD
    const updated = {
      ...preferences,
      widget_dashboard: {
        ...dashboard,
        widgets: dashboard.widgets.map((w) =>
          w.id === widgetId ? { ...w, config: { ...w.config, ...config } } : w
        ),
      },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },

  updateWidgetTitle: (widgetId: string, title: string) => {
    const { preferences } = get()
    const dashboard = preferences.widget_dashboard ?? DEFAULT_WIDGET_DASHBOARD
    const updated = {
      ...preferences,
      widget_dashboard: {
        ...dashboard,
        widgets: dashboard.widgets.map((w) =>
          w.id === widgetId ? { ...w, title } : w
        ),
      },
    }
    set({ preferences: updated })
    debouncedSave(updated)
  },
}))
