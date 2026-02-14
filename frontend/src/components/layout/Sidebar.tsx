import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  Server,
  Boxes,
  Play,
  DollarSign,
  Users,
  Shield,
  ScrollText,
  ChevronLeft,
  ChevronRight,
  Hexagon,
  Clock,
  HeartPulse,
  GitCompare,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/uiStore'
import { useHasPermission } from '@/lib/permissions'
import { useInventoryStore } from '@/stores/inventoryStore'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'

interface NavItem {
  label: string
  href: string
  icon: React.ReactNode
  permission?: string
  section?: 'main' | 'admin'
}

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useUIStore((s) => s.toggleSidebar)
  const location = useLocation()
  const types = useInventoryStore((s) => s.types)

  const mainNav: NavItem[] = [
    { label: 'Dashboard', href: '/dashboard', icon: <LayoutDashboard className="h-4 w-4" /> },
    { label: 'Services', href: '/services', icon: <Boxes className="h-4 w-4" />, permission: 'services.view' },
    { label: 'Inventory', href: '/inventory', icon: <Server className="h-4 w-4" /> },
    { label: 'Jobs', href: '/jobs', icon: <Play className="h-4 w-4" /> },
    { label: 'Schedules', href: '/schedules', icon: <Clock className="h-4 w-4" />, permission: 'schedules.view' },
    { label: 'Costs', href: '/costs', icon: <DollarSign className="h-4 w-4" />, permission: 'costs.view' },
    { label: 'Health', href: '/health', icon: <HeartPulse className="h-4 w-4" />, permission: 'health.view' },
    { label: 'Drift Detection', href: '/drift', icon: <GitCompare className="h-4 w-4" />, permission: 'drift.view' },
  ]

  const adminNav: NavItem[] = [
    { label: 'Users', href: '/users', icon: <Users className="h-4 w-4" />, permission: 'users.view' },
    { label: 'Roles', href: '/roles', icon: <Shield className="h-4 w-4" />, permission: 'roles.view' },
    { label: 'Audit Log', href: '/audit', icon: <ScrollText className="h-4 w-4" />, permission: 'system.audit_log' },
  ]

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

        {/* Collapse toggle */}
        <div className="border-t border-sidebar-border p-2">
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
