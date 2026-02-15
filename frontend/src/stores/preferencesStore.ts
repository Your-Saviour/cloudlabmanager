import { create } from 'zustand'
import api from '@/lib/api'
import type { UserPreferences, CustomLink } from '@/types/preferences'
import { DEFAULT_PREFERENCES } from '@/types/preferences'

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
      set({ preferences: merged, loaded: true })
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
}))
