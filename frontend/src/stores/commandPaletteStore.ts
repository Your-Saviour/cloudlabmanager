import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface RecentItem {
  id: string
  label: string
  icon: string
  href: string
  timestamp: number
}

interface CommandPaletteState {
  recentItems: RecentItem[]
  addRecentItem: (item: Omit<RecentItem, 'timestamp'>) => void
  clearRecent: () => void
}

export const useCommandPaletteStore = create<CommandPaletteState>()(
  persist(
    (set, get) => ({
      recentItems: [],

      addRecentItem: (item) => {
        const { recentItems } = get()
        const filtered = recentItems.filter(r => r.id !== item.id)
        const updated = [{ ...item, timestamp: Date.now() }, ...filtered].slice(0, 10)
        set({ recentItems: updated })
      },

      clearRecent: () => set({ recentItems: [] }),
    }),
    {
      name: 'cloudlab-command-palette',
      partialize: (state) => ({ recentItems: state.recentItems }),
    }
  )
)
