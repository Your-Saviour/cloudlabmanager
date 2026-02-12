import { useAuthStore } from '@/stores/authStore'

export function hasPermission(codename: string): boolean {
  const { user } = useAuthStore.getState()
  if (!user || !user.permissions) return false
  if (user.permissions.includes('*')) return true
  return user.permissions.includes(codename)
}

export function useHasPermission(codename: string): boolean {
  const permissions = useAuthStore((s) => s.user?.permissions)
  if (!permissions) return false
  if (permissions.includes('*')) return true
  return permissions.includes(codename)
}
