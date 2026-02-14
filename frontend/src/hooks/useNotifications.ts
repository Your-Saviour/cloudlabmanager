import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

export interface Notification {
  id: number
  title: string
  body: string | null
  event_type: string
  severity: 'info' | 'success' | 'warning' | 'error'
  action_url: string | null
  is_read: boolean
  created_at: string
}

export function useUnreadCount() {
  return useQuery({
    queryKey: ['notifications-count'],
    queryFn: async () => {
      const { data } = await api.get('/api/notifications/count')
      return data as { unread: number }
    },
    refetchInterval: 30000,
  })
}

export function useNotifications(limit = 20) {
  return useQuery({
    queryKey: ['notifications', limit],
    queryFn: async () => {
      const { data } = await api.get(`/api/notifications?limit=${limit}`)
      return data as { notifications: Notification[]; total: number }
    },
  })
}

export function useMarkRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post(`/api/notifications/${id}/read`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications-count'] })
      qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}

export function useMarkAllRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post('/api/notifications/read-all'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications-count'] })
      qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}
