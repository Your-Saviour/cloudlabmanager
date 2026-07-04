import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

// All /api/vpc mutations are async jobs — the backend resyncs the report when
// the job finishes, so we invalidate immediately and rely on the report
// query's refetchInterval to pick up the final state.
export function useVpcJobMutation<TVars>(options: {
  mutationFn: (vars: TVars) => Promise<{ job_id?: string }>
  successMessage: string
  errorMessage: string
  onSuccess?: () => void
}) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: options.mutationFn,
    onSuccess: () => {
      toast.success(options.successMessage)
      queryClient.invalidateQueries({ queryKey: ['vpc', 'report'] })
      options.onSuccess?.()
    },
    onError: () => toast.error(options.errorMessage),
  })
}
