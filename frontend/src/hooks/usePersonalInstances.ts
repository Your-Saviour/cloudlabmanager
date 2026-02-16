import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

export interface PersonalInstance {
  hostname: string
  ip_address: string
  region: string
  plan: string
  power_status: string
  vultr_id: string
  owner: string
  service: string
  ttl_hours: number | null
  inventory_object_id: number
  created_at: string | null
  outputs: Array<{
    name: string
    type: string
    label: string
    value: string
    username?: string
    credential_type?: string
  }>
}

export interface PersonalInstanceConfig {
  default_plan: string
  default_region: string
  default_ttl_hours: number
  max_per_user: number
  hostname_template: string
  required_inputs: Array<{
    name: string
    label: string
    type: string
    description?: string
    required?: boolean
  }>
}

export interface PersonalService {
  service: string
  config: PersonalInstanceConfig
}

// List all services with personal instances enabled
export function usePersonalServices() {
  return useQuery({
    queryKey: ['personal-instances', 'services'],
    queryFn: async () => {
      const { data } = await api.get('/api/personal-instances/services')
      return data.services as PersonalService[]
    },
    staleTime: 60000,
  })
}

// List personal instances (optionally filtered by service)
export function usePersonalInstances(service?: string) {
  return useQuery({
    queryKey: ['personal-instances', service ?? 'all'],
    queryFn: async () => {
      const params = service ? `?service=${encodeURIComponent(service)}` : ''
      const { data } = await api.get(`/api/personal-instances${params}`)
      return data.hosts as PersonalInstance[]
    },
    refetchInterval: 10000,
  })
}

// Get config for a specific service
export function usePersonalInstanceConfig(service: string) {
  return useQuery({
    queryKey: ['personal-instances', 'config', service],
    queryFn: async () => {
      const { data } = await api.get(`/api/personal-instances/config?service=${encodeURIComponent(service)}`)
      return data as PersonalInstanceConfig
    },
    staleTime: 60000,
    enabled: !!service,
  })
}

// Create a personal instance
export function useCreatePersonalInstance() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (params: { service: string; region?: string; inputs?: Record<string, any> }) => {
      const { data } = await api.post('/api/personal-instances', params)
      return data as { job_id: string; hostname: string }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['personal-instances'] })
    },
  })
}

// Destroy a personal instance
export function useDestroyPersonalInstance() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (hostname: string) => {
      const { data } = await api.delete(`/api/personal-instances/${encodeURIComponent(hostname)}`)
      return data as { job_id: string }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['personal-instances'] })
    },
  })
}

// Extend TTL
export function useExtendPersonalInstanceTTL() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (hostname: string) => {
      const { data } = await api.post(`/api/personal-instances/${encodeURIComponent(hostname)}/extend`, {})
      return data as { hostname: string; ttl_hours: number; extended_at: string }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['personal-instances'] })
    },
  })
}
