import axios, { type AxiosError } from 'axios'
import { useAuthStore } from '@/stores/authStore'

const api = axios.create({
  baseURL: '',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api

// --- Bug Reports ---

export async function submitBugReport(formData: FormData) {
  const res = await api.post('/api/bug-reports', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

export async function getMyBugReports(params?: { page?: number; per_page?: number }) {
  const res = await api.get('/api/bug-reports/mine', { params })
  return res.data
}

export async function getAllBugReports(params?: {
  page?: number; per_page?: number; search?: string; status?: string; severity?: string
}) {
  const res = await api.get('/api/bug-reports', { params })
  return res.data
}

export async function getBugReport(id: number) {
  const res = await api.get(`/api/bug-reports/${id}`)
  return res.data
}

export async function updateBugReport(id: number, data: { status?: string; admin_notes?: string }) {
  const res = await api.put(`/api/bug-reports/${id}`, data)
  return res.data
}
