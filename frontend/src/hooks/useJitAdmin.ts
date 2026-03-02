import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

export interface AdUserEntry {
  sam_account_name: string
  display_name: string | null
  enabled: boolean
  distinguished_name: string | null
  groups: string[]
  synced_at: string | null
}

export interface AdGroupEntry {
  name: string
  group_scope: string | null
  group_category: string | null
  description: string | null
  member_count: number
  synced_at: string | null
}

export interface JitGrant {
  id: number
  target_username: string
  ad_group: string
  workflow: 'self_service' | 'request_approval' | 'admin_grant'
  status: 'pending_approval' | 'active' | 'expired' | 'revoked' | 'denied' | 'failed'
  duration_minutes: number
  activated_at: string | null
  expires_at: string | null
  revoked_at: string | null
  reason: string | null
  denial_reason: string | null
  requested_by: number | null
  requested_by_username: string | null
  requested_at: string
  approved_by: number | null
  approved_by_username: string | null
  approved_at: string | null
  service_name: string
  elevate_job_id: string | null
  revoke_job_id: string | null
}

export function useJitGrants(status?: string) {
  return useQuery({
    queryKey: ['jit-grants', status ?? 'all'],
    queryFn: async () => {
      const params = status ? `?status=${encodeURIComponent(status)}` : ''
      const { data } = await api.get(`/api/jit/grants${params}`)
      return data.grants as JitGrant[]
    },
    refetchInterval: 15000,
  })
}

export function useJitHistory(page: number = 1) {
  return useQuery({
    queryKey: ['jit-grants', 'history', page],
    queryFn: async () => {
      const { data } = await api.get(`/api/jit/grants/history?page=${page}`)
      return data as { grants: JitGrant[]; total: number; page: number; page_size: number }
    },
  })
}

export function useJitConfig() {
  return useQuery({
    queryKey: ['jit-config'],
    queryFn: async () => {
      const { data } = await api.get('/api/jit/ad-groups')
      return data as { groups: string[]; durations: number[]; live_groups: AdGroupEntry[] }
    },
    staleTime: 60000,
  })
}

export function useAdUsers(search?: string) {
  const [debouncedSearch, setDebouncedSearch] = useState(search ?? '')

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search ?? ''), 300)
    return () => clearTimeout(timer)
  }, [search])

  return useQuery({
    queryKey: ['ad-users', debouncedSearch],
    queryFn: async () => {
      const params = debouncedSearch ? `?search=${encodeURIComponent(debouncedSearch)}` : ''
      const { data } = await api.get(`/api/jit/ad-users${params}`)
      return data.users as AdUserEntry[]
    },
    staleTime: 30000,
  })
}

export function useAdGroups() {
  return useQuery({
    queryKey: ['ad-groups-live'],
    queryFn: async () => {
      const { data } = await api.get('/api/jit/ad-groups/live')
      return data.groups as AdGroupEntry[]
    },
    staleTime: 30000,
  })
}

export function useAdSync() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/api/jit/ad-sync')
      return data as { users: number; groups: number; error?: string; skipped?: boolean }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ad-users'] })
      qc.invalidateQueries({ queryKey: ['ad-groups-live'] })
      qc.invalidateQueries({ queryKey: ['jit-config'] })
    },
  })
}

export function useCreateJitGrant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (params: {
      target_username: string
      ad_group: string
      duration_minutes: number
      reason?: string
      workflow?: string
    }) => {
      const { data } = await api.post('/api/jit/grants', params)
      return data as { grant: JitGrant; job_id: string | null }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jit-grants'] })
    },
  })
}

export function useAdminJitGrant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (params: {
      target_username: string
      ad_group: string
      duration_minutes: number
      reason?: string
    }) => {
      const { data } = await api.post('/api/jit/grants/admin', params)
      return data as { grant: JitGrant; job_id: string | null }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jit-grants'] })
    },
  })
}

export function useApproveJitGrant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (grantId: number) => {
      const { data } = await api.post(`/api/jit/grants/${grantId}/approve`)
      return data as { grant: JitGrant; job_id: string | null }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jit-grants'] })
    },
  })
}

export function useDenyJitGrant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (params: { grantId: number; reason?: string }) => {
      const { data } = await api.post(`/api/jit/grants/${params.grantId}/deny`, {
        reason: params.reason,
      })
      return data as { grant: JitGrant }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jit-grants'] })
    },
  })
}

export function useRevokeJitGrant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (grantId: number) => {
      const { data } = await api.post(`/api/jit/grants/${grantId}/revoke`)
      return data as { grant: JitGrant; job_id: string | null }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jit-grants'] })
    },
  })
}
