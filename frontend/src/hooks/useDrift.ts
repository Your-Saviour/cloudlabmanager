import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

export interface DriftInstance {
  service: string
  hostname: string
  status: 'in_sync' | 'drifted' | 'missing' | 'unknown'
  expected: Record<string, unknown>
  actual: Record<string, unknown> | null
  diffs: { field: string; expected: unknown; actual: unknown }[]
  dns: {
    status: 'match' | 'mismatch' | 'missing' | 'unknown'
    expected_ip: string | null
    actual_ip: string | null
  } | null
  region: string
  plan: string
}

export interface OrphanedInstance {
  hostname: string
  vultr_id: string
  plan: string
  region: string
  tags: string[]
}

export interface DriftReport {
  id: number
  status: 'in_sync' | 'drifted' | 'error'
  created_at: string
  summary: {
    total: number
    in_sync: number
    drifted: number
    missing: number
    orphaned: number
  }
  instances: DriftInstance[]
  orphaned: OrphanedInstance[]
}

export interface DriftSummary {
  total: number
  in_sync: number
  drifted: number
  missing: number
  orphaned: number
  last_checked: string | null
}

export function useDriftStatus() {
  return useQuery({
    queryKey: ['drift', 'status'],
    queryFn: async () => {
      const { data } = await api.get('/api/drift/status')
      return data as { status: string; last_checked: string | null; checking: boolean }
    },
    refetchInterval: 30000,
  })
}

export function useDriftSummary() {
  return useQuery({
    queryKey: ['drift', 'summary'],
    queryFn: async () => {
      const { data } = await api.get('/api/drift/summary')
      return data as DriftSummary
    },
    refetchInterval: 30000,
  })
}

export function useDriftHistory(limit?: number) {
  return useQuery({
    queryKey: ['drift', 'history', limit],
    queryFn: async () => {
      const params = limit ? { limit } : {}
      const { data } = await api.get('/api/drift/history', { params })
      return data as DriftReport[]
    },
    refetchInterval: 30000,
  })
}

export function useDriftReport(reportId: number | null) {
  return useQuery({
    queryKey: ['drift', 'report', reportId],
    queryFn: async () => {
      const { data } = await api.get(`/api/drift/reports/${reportId}`)
      return data as DriftReport
    },
    enabled: reportId != null,
  })
}

export function useDriftCheck() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/api/drift/check')
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['drift'] })
    },
  })
}
