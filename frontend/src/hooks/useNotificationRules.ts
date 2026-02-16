import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

export interface NotificationRule {
  id: number
  name: string
  event_type: string
  channel: 'in_app' | 'email' | 'slack'
  channel_id: number | null
  role_id: number | null
  filters: Record<string, unknown> | null
  is_enabled: boolean
  created_at: string
  updated_at: string
}

export interface NotificationChannel {
  id: number
  name: string
  channel_type: 'slack'
  config: { webhook_url: string }
  is_enabled: boolean
  created_at: string
  updated_at: string
}

export interface EventType {
  value: string
  label: string
}

// Rules
export function useNotificationRules() {
  return useQuery({
    queryKey: ['notification-rules'],
    queryFn: async () => {
      const { data } = await api.get('/api/notifications/rules')
      return data as { rules: NotificationRule[] }
    },
  })
}

export function useCreateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      name: string
      event_type: string
      channel: string
      channel_id?: number | null
      role_id?: number | null
      filters?: Record<string, unknown> | null
      is_enabled?: boolean
    }) => api.post('/api/notifications/rules', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notification-rules'] })
    },
  })
}

export function useUpdateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<{
      name: string
      event_type: string
      channel: string
      channel_id: number | null
      role_id: number | null
      filters: Record<string, unknown> | null
      is_enabled: boolean
    }>) => api.put(`/api/notifications/rules/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notification-rules'] })
    },
  })
}

export function useDeleteRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/api/notifications/rules/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notification-rules'] })
    },
  })
}

export function useEventTypes() {
  return useQuery({
    queryKey: ['notification-event-types'],
    queryFn: async () => {
      const { data } = await api.get('/api/notifications/rules/event-types')
      return data as { event_types: EventType[] }
    },
  })
}

// Channels
export function useNotificationChannels() {
  return useQuery({
    queryKey: ['notification-channels'],
    queryFn: async () => {
      const { data } = await api.get('/api/notifications/channels')
      return data as { channels: NotificationChannel[] }
    },
  })
}

export function useCreateChannel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      name: string
      channel_type: string
      config: { webhook_url: string }
      is_enabled?: boolean
    }) => api.post('/api/notifications/channels', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notification-channels'] })
    },
  })
}

export function useUpdateChannel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<{
      name: string
      channel_type: string
      config: { webhook_url: string }
      is_enabled: boolean
    }>) => api.put(`/api/notifications/channels/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notification-channels'] })
    },
  })
}

export function useDeleteChannel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/api/notifications/channels/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notification-channels'] })
    },
  })
}

export function useTestChannel() {
  return useMutation({
    mutationFn: (id: number) => api.post(`/api/notifications/channels/${id}/test`),
  })
}

// Email transport
export interface EmailTransportStatus {
  transport: 'smtp' | 'sendamatic'
  configured: boolean
  host?: string
  port?: number
  tls?: boolean
}

export function useEmailTransportStatus() {
  return useQuery({
    queryKey: ['email-transport-status'],
    queryFn: async () => {
      const { data } = await api.get('/api/notifications/email/status')
      return data as EmailTransportStatus
    },
  })
}

export function useTestEmail() {
  return useMutation({
    mutationFn: () => api.post('/api/notifications/email/test'),
  })
}
