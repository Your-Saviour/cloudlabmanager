import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/authStore'
import { useInventoryStore } from '@/stores/inventoryStore'
import api from '@/lib/api'

export function useAuthStatus() {
  return useQuery({
    queryKey: ['auth', 'status'],
    queryFn: async () => {
      const { data } = await api.get('/api/auth/status')
      return data as { setup_complete: boolean; vault_set: boolean }
    },
    staleTime: 30000,
  })
}

export function useCurrentUser() {
  const token = useAuthStore((s) => s.token)
  const setUser = useAuthStore((s) => s.setUser)
  const setTypes = useInventoryStore((s) => s.setTypes)

  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: async () => {
      const { data } = await api.get('/api/auth/me')
      const u = data.user || data
      const user = {
        id: u.id,
        username: u.username,
        display_name: u.display_name,
        email: u.email,
        permissions: u.permissions || data.permissions || [],
      }
      setUser(user)
      return user
    },
    enabled: !!token,
    staleTime: 60000,
  })
}

export function useInventoryTypes() {
  const token = useAuthStore((s) => s.token)
  const setTypes = useInventoryStore((s) => s.setTypes)

  return useQuery({
    queryKey: ['inventory', 'types'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/types')
      const types = data.types || []
      setTypes(types)
      return types
    },
    enabled: !!token,
    staleTime: 300000,
  })
}
