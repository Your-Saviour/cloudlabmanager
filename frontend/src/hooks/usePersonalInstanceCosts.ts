import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

export interface PersonalInstanceCostEntry {
  hostname: string
  owner: string | null
  service: string | null
  region: string
  plan: string
  created_at: string | null
  expires_at: string | null
  ttl_hours: number | null
  ttl_remaining_hours: number | null
  hourly_cost: number
  monthly_cost: number
  cost_accrued: number
  expected_remaining_cost: number
  pricing_available: boolean
}

export interface PersonalInstanceHistoryEntry {
  hostname: string
  owner: string | null
  service: string | null
  plan: string
  region: string
  first_seen: string
  last_seen: string
  duration_hours: number
  estimated_total_cost: number
  pricing_available: boolean
}

export interface PersonalInstanceCostResponse {
  active: PersonalInstanceCostEntry[]
  historical: PersonalInstanceHistoryEntry[]
  summary: {
    active_count: number
    total_monthly_rate: number
    total_remaining_cost: number
  }
  view_all: boolean
}

export function usePersonalInstanceCosts() {
  return useQuery({
    queryKey: ['costs', 'personal-instances'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs/personal-instances')
      return data as PersonalInstanceCostResponse
    },
    refetchInterval: 30000,
  })
}
