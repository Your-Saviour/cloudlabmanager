import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/uiStore'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { useJobCompletionWatcher } from '@/hooks/useJobCompletionWatcher'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { CommandPalette } from './CommandPalette'
import { SubmitFeedbackModal } from '@/components/feedback/SubmitFeedbackModal'

export function AppLayout() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const reportBugOpen = useUIStore((s) => s.reportBugOpen)
  const setReportBugOpen = useUIStore((s) => s.setReportBugOpen)
  const loadPreferences = usePreferencesStore((s) => s.loadPreferences)
  const prefsLoaded = usePreferencesStore((s) => s.loaded)
  const location = useLocation()
  useKeyboardShortcuts()
  useJobCompletionWatcher()

  useEffect(() => {
    if (!prefsLoaded) loadPreferences()
  }, [prefsLoaded, loadPreferences])

  return (
    <div className="min-h-screen">
      <Sidebar />
      <div className={cn('transition-all duration-300', collapsed ? 'ml-16' : 'ml-60')}>
        <Header />
        <main className="p-6">
          <div key={location.pathname} className="animate-page-enter">
            <Outlet />
          </div>
        </main>
      </div>
      <CommandPalette />
      <SubmitFeedbackModal open={reportBugOpen} onClose={() => setReportBugOpen(false)} type="bug_report" />
    </div>
  )
}
