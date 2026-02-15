import { useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/uiStore'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { CommandPalette } from './CommandPalette'

export function AppLayout() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const loadPreferences = usePreferencesStore((s) => s.loadPreferences)
  const prefsLoaded = usePreferencesStore((s) => s.loaded)
  useKeyboardShortcuts()

  useEffect(() => {
    if (!prefsLoaded) loadPreferences()
  }, [prefsLoaded, loadPreferences])

  return (
    <div className="min-h-screen">
      <Sidebar />
      <div className={cn('transition-all duration-300', collapsed ? 'ml-16' : 'ml-60')}>
        <Header />
        <main className="p-6">
          <Outlet />
        </main>
      </div>
      <CommandPalette />
    </div>
  )
}
