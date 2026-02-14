import { useState } from 'react'
import { Bell, CheckCheck, Info, CheckCircle, AlertTriangle, XCircle } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useUnreadCount, useNotifications, useMarkRead, useMarkAllRead } from '@/hooks/useNotifications'
import type { Notification } from '@/hooks/useNotifications'
import { useNavigate } from 'react-router-dom'
import { cn, relativeTime } from '@/lib/utils'
import { useQueryClient } from '@tanstack/react-query'

const severityConfig: Record<Notification['severity'], { icon: typeof Info; className: string }> = {
  info: { icon: Info, className: 'text-blue-400' },
  success: { icon: CheckCircle, className: 'text-green-400' },
  warning: { icon: AlertTriangle, className: 'text-yellow-400' },
  error: { icon: XCircle, className: 'text-red-400' },
}

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: countData } = useUnreadCount()
  const { data: notifData } = useNotifications()
  const markRead = useMarkRead()
  const markAllRead = useMarkAllRead()

  const unread = countData?.unread ?? 0
  const notifications = notifData?.notifications ?? []

  const handleOpenChange = (isOpen: boolean) => {
    setOpen(isOpen)
    if (isOpen) {
      qc.invalidateQueries({ queryKey: ['notifications'] })
    }
  }

  const handleClick = (notification: Notification) => {
    if (!notification.is_read) {
      markRead.mutate(notification.id)
    }
    if (notification.action_url) {
      setOpen(false)
      navigate(notification.action_url)
    }
  }

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="relative h-8 w-8 p-0" aria-label={unread > 0 ? `Notifications (${unread} unread)` : 'Notifications'}>
          <Bell className="h-4 w-4" />
          {unread > 0 && (
            <span aria-hidden="true" className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
              {unread > 99 ? '99+' : unread}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[360px] p-0">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h4 className="text-sm font-semibold">Notifications</h4>
          {unread > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-auto gap-1 px-2 py-1 text-xs text-muted-foreground"
              onClick={() => markAllRead.mutate()}
            >
              <CheckCheck className="h-3 w-3" />
              Mark all read
            </Button>
          )}
        </div>
        <ScrollArea className="max-h-[400px]">
          {notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
              <Bell className="mb-2 h-8 w-8 opacity-30" />
              <p className="text-sm">No notifications</p>
            </div>
          ) : (
            <div className="divide-y">
              {notifications.map((n) => {
                const config = severityConfig[n.severity]
                const Icon = config.icon
                return (
                  <button
                    key={n.id}
                    onClick={() => handleClick(n)}
                    className={cn(
                      'flex w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
                      !n.is_read && 'bg-accent/20'
                    )}
                  >
                    <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', config.className)} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <p className={cn('text-sm', !n.is_read && 'font-medium')}>
                          {n.title}
                        </p>
                        {!n.is_read && (
                          <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-blue-400" />
                        )}
                      </div>
                      {n.body && (
                        <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                          {n.body}
                        </p>
                      )}
                      <p className="mt-1 text-xs text-muted-foreground">
                        {relativeTime(n.created_at)}
                      </p>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  )
}
