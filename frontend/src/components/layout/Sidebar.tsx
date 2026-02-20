import { createElement } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  Bug,
  ChevronLeft,
  ChevronRight,
  Hexagon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/uiStore'
import { useHasPermission } from '@/lib/permissions'
import { useInventoryStore } from '@/stores/inventoryStore'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { mainRoutes, toolRoutes, adminRoutes, routeIcons } from '@/lib/routes'

interface NavItem {
  label: string
  href: string
  icon: React.ReactNode
  permission?: string
}

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useUIStore((s) => s.toggleSidebar)
  const setReportBugOpen = useUIStore((s) => s.setReportBugOpen)
  const location = useLocation()
  const types = useInventoryStore((s) => s.types)

  const mainNav: NavItem[] = mainRoutes.map((r) => ({
    label: r.label,
    href: r.href,
    icon: createElement(routeIcons[r.icon], { className: 'h-4 w-4' }),
    permission: r.permission,
  }))

  const toolNav: NavItem[] = toolRoutes.map((r) => ({
    label: r.label,
    href: r.href,
    icon: createElement(routeIcons[r.icon], { className: 'h-4 w-4' }),
    permission: r.permission,
  }))

  const adminNav: NavItem[] = adminRoutes.map((r) => ({
    label: r.label,
    href: r.href,
    icon: createElement(routeIcons[r.icon], { className: 'h-4 w-4' }),
    permission: r.permission,
  }))

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 h-screen border-r bg-sidebar transition-all duration-300',
        collapsed ? 'w-16' : 'w-60'
      )}
    >
      <div className="flex h-full flex-col">
        {/* Brand */}
        <div className="flex h-14 items-center border-b border-sidebar-border px-4">
          <div className="flex items-center gap-3">
            <Hexagon className="h-6 w-6 text-primary shrink-0" />
            {!collapsed && (
              <div className="flex flex-col leading-none">
                <span className="text-sm font-bold tracking-wider text-foreground">CLOUDLAB</span>
                <span className="text-[10px] font-medium tracking-widest text-muted-foreground">MANAGER</span>
              </div>
            )}
          </div>
        </div>

        {/* Navigation */}
        <ScrollArea className="flex-1 py-4">
          <nav className="space-y-1 px-2">
            {mainNav.map((item) => (
              <SidebarLink key={item.href} item={item} collapsed={collapsed} />
            ))}
          </nav>

          <Separator className="my-4 mx-2" />

          <div className="px-2">
            {!collapsed && (
              <p className="px-3 mb-2 text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
                Tools
              </p>
            )}
            <nav className="space-y-1">
              {toolNav.map((item) => (
                <SidebarLink key={item.href} item={item} collapsed={collapsed} />
              ))}
            </nav>
          </div>

          <Separator className="my-4 mx-2" />

          <div className="px-2">
            {!collapsed && (
              <p className="px-3 mb-2 text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
                Admin
              </p>
            )}
            <nav className="space-y-1">
              {adminNav.map((item) => (
                <SidebarLink key={item.href} item={item} collapsed={collapsed} />
              ))}
            </nav>
          </div>
        </ScrollArea>

        {/* Footer */}
        <div className="border-t border-sidebar-border p-2 space-y-1">
          {collapsed ? (
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="w-full h-8 text-muted-foreground hover:text-foreground"
                  onClick={() => setReportBugOpen(true)}
                  aria-label="Report Bug"
                >
                  <Bug className="h-4 w-4 shrink-0" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">Report Bug</TooltipContent>
            </Tooltip>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="w-full h-8 text-muted-foreground hover:text-foreground gap-2 justify-start"
              onClick={() => setReportBugOpen(true)}
            >
              <Bug className="h-4 w-4 shrink-0" />
              <span className="text-xs">Report Bug</span>
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="w-full h-8 text-muted-foreground hover:text-foreground"
            onClick={toggleSidebar}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </aside>
  )
}

function SidebarLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const hasPermission = useHasPermission(item.permission || '')
  if (item.permission && !hasPermission) return null

  const link = (
    <NavLink
      to={item.href}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
          'text-sidebar-foreground hover:bg-sidebar-accent/10 hover:text-sidebar-accent-foreground',
          isActive && 'bg-sidebar-accent/15 text-primary',
          collapsed && 'justify-center px-0'
        )
      }
    >
      {item.icon}
      {!collapsed && <span>{item.label}</span>}
    </NavLink>
  )

  if (collapsed) {
    return (
      <Tooltip delayDuration={0}>
        <TooltipTrigger asChild>{link}</TooltipTrigger>
        <TooltipContent side="right">{item.label}</TooltipContent>
      </Tooltip>
    )
  }

  return link
}
