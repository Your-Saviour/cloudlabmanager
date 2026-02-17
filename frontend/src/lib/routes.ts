import {
  LayoutDashboard,
  Compass,
  Boxes,
  Server,
  Play,
  Clock,
  DollarSign,
  HeartPulse,
  GitCompare,
  Webhook,
  Users,
  Shield,
  ScrollText,
  Bell,
  User,
  Camera,
  OctagonX,
  UserPlus,
  Rocket,
  PlayCircle,
  SquareTerminal,
  Monitor,
  Bug,
  MessageSquareMore,
  type LucideIcon,
} from 'lucide-react'

export interface RouteDefinition {
  label: string
  href: string
  icon: string
  permission?: string
  section: 'main' | 'admin' | 'quick'
  keywords?: string[]
}

export const routeIcons: Record<string, LucideIcon> = {
  LayoutDashboard,
  Compass,
  Boxes,
  Server,
  Play,
  Clock,
  DollarSign,
  Camera,
  HeartPulse,
  GitCompare,
  Webhook,
  Users,
  Shield,
  ScrollText,
  Bell,
  User,
  OctagonX,
  UserPlus,
  Rocket,
  PlayCircle,
  SquareTerminal,
  Monitor,
  Bug,
  MessageSquareMore,
}

export const mainRoutes: RouteDefinition[] = [
  { label: 'Dashboard', href: '/dashboard', icon: 'LayoutDashboard', section: 'main', keywords: ['home', 'overview'] },
  { label: 'Portal', href: '/portal', icon: 'Compass', section: 'main', permission: 'portal.view', keywords: ['access', 'links', 'bookmarks'] },
  { label: 'My Instances', href: '/personal-instances', icon: 'Monitor', section: 'main', permission: 'personal_instances.create', keywords: ['personal', 'instance', 'my', 'jump', 'terminal', 'browser'] },
  { label: 'Services', href: '/services', icon: 'Boxes', section: 'main', permission: 'services.view', keywords: ['deploy', 'stop', 'manage'] },
  { label: 'Inventory', href: '/inventory', icon: 'Server', section: 'main', keywords: ['servers', 'instances', 'objects'] },
  { label: 'Jobs', href: '/jobs', icon: 'Play', section: 'main', keywords: ['tasks', 'running', 'logs', 'history'] },
  { label: 'Schedules', href: '/schedules', icon: 'Clock', section: 'main', permission: 'schedules.view', keywords: ['cron', 'timer', 'recurring'] },
  { label: 'Costs', href: '/costs', icon: 'DollarSign', section: 'main', permission: 'costs.view', keywords: ['budget', 'billing', 'spend', 'money'] },
  { label: 'Snapshots', href: '/snapshots', icon: 'Camera', section: 'main', permission: 'snapshots.view', keywords: ['snapshot', 'backup', 'restore', 'image'] },
  { label: 'Health', href: '/health', icon: 'HeartPulse', section: 'main', permission: 'health.view', keywords: ['status', 'monitoring', 'uptime'] },
  { label: 'Drift Detection', href: '/drift', icon: 'GitCompare', section: 'main', permission: 'drift.view', keywords: ['drift', 'changes', 'compare', 'diff'] },
  { label: 'Webhooks', href: '/webhooks', icon: 'Webhook', section: 'main', permission: 'webhooks.view', keywords: ['hooks', 'triggers', 'api'] },
]

export const adminRoutes: RouteDefinition[] = [
  { label: 'Users', href: '/users', icon: 'Users', section: 'admin', permission: 'users.view', keywords: ['accounts', 'people'] },
  { label: 'Roles', href: '/roles', icon: 'Shield', section: 'admin', permission: 'roles.view', keywords: ['permissions', 'rbac', 'access'] },
  { label: 'Audit Log', href: '/audit', icon: 'ScrollText', section: 'admin', permission: 'system.audit_log', keywords: ['log', 'activity', 'history', 'events'] },
  { label: 'Notifications', href: '/notifications/rules', icon: 'Bell', section: 'admin', permission: 'notifications.rules.view', keywords: ['alerts', 'rules', 'channels'] },
  { label: 'Feedback', href: '/feedback', icon: 'MessageSquareMore', section: 'admin', permission: 'feedback.view_all', keywords: ['feature', 'bug', 'request', 'feedback'] },
]

export const quickRoutes: RouteDefinition[] = [
  { label: 'Profile Settings', href: '/profile', icon: 'User', section: 'quick', keywords: ['account', 'settings', 'preferences'] },
]
