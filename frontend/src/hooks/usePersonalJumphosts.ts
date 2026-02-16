import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

export interface PersonalJumphost {
  hostname: string
  ip_address: string
  region: string
  plan: string
  power_status: string
  vultr_id: string
  owner: string
  ttl_hours: number | null
  inventory_object_id: number
  created_at: string | null
}

export interface PersonalJumphostConfig {
  default_plan: string
  default_region: string
  default_ttl_hours: number
  max_per_user: number
}

export function usePersonalJumphosts() {
  return useQuery({
    queryKey: ['personal-jumphosts'],
    queryFn: async () => {
      const { data } = await api.get('/api/personal-jumphosts')
      return data.hosts as PersonalJumphost[]
    },
    refetchInterval: 10000,
  })
}

export function usePersonalJumphostConfig() {
  return useQuery({
    queryKey: ['personal-jumphosts', 'config'],
    queryFn: async () => {
      const { data } = await api.get('/api/personal-jumphosts/config')
      return data as PersonalJumphostConfig
    },
    staleTime: 60000,
  })
}

export function useCreateJumphost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (region?: string) => {
      const { data } = await api.post('/api/personal-jumphosts', { region: region || null })
      return data as { job_id: string; hostname: string }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['personal-jumphosts'] })
    },
  })
}

export function useDestroyJumphost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (hostname: string) => {
      const { data } = await api.delete(`/api/personal-jumphosts/${encodeURIComponent(hostname)}`)
      return data as { job_id: string }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['personal-jumphosts'] })
    },
  })
}

export function useExtendJumphostTTL() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (hostname: string) => {
      const { data } = await api.post(`/api/personal-jumphosts/${encodeURIComponent(hostname)}/extend`, {})
      return data as { hostname: string; ttl_hours: number; extended_at: string }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['personal-jumphosts'] })
    },
  })
}
