import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

export interface VultrPlan {
  id: string
  vcpu_count: number
  ram: number
  disk: number
  monthly_cost: number
  hourly_cost: number
  bandwidth: number
}

export function useVc2Plans() {
  return useQuery({
    queryKey: ['plans', 'vc2'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs/plans/vc2')
      return data.plans as VultrPlan[]
    },
    staleTime: 5 * 60 * 1000,
  })
}
