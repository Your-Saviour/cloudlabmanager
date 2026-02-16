import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getMyBugReports, getAllBugReports, getBugReport, submitBugReport, updateBugReport } from '@/lib/api'
import { toast } from 'sonner'

export function useMyBugReports(page?: number, perPage?: number) {
  return useQuery({
    queryKey: ['bug-reports', 'mine', page, perPage],
    queryFn: () => getMyBugReports({ page: page!, per_page: perPage! }),
    enabled: page != null && perPage != null,
  })
}

export function useAllBugReports(params: {
  page?: number; per_page?: number; search?: string; status?: string; severity?: string; enabled?: boolean
} = {}) {
  const { enabled, ...queryParams } = params
  return useQuery({
    queryKey: ['bug-reports', 'all', queryParams],
    queryFn: () => getAllBugReports(queryParams),
    enabled: enabled !== false,
  })
}

export function useBugReport(id: number) {
  return useQuery({
    queryKey: ['bug-reports', id],
    queryFn: () => getBugReport(id),
    enabled: id > 0,
  })
}

export function useSubmitBugReport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: submitBugReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bug-reports'] })
      toast.success('Bug report submitted successfully')
    },
    onError: () => {
      toast.error('Failed to submit bug report')
    },
  })
}

export function useUpdateBugReport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number; status?: string; admin_notes?: string }) =>
      updateBugReport(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bug-reports'] })
      toast.success('Bug report updated')
    },
    onError: () => {
      toast.error('Failed to update bug report')
    },
  })
}
