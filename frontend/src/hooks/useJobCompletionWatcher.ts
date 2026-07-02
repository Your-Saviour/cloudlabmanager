import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import api from '@/lib/api'
import type { Job } from '@/types'

const INVALIDATE_KEYS = [
  ['inventory'],
  ['services'],
  ['active-deployments'],
  ['service-summaries'],
  ['jobs'],
]

function shouldToast(job: Job): boolean {
  // User is watching this job live on its detail page
  if (window.location.pathname === `/jobs/${job.id}`) return false
  if (job.status === 'failed') return true
  // Scheduled/webhook successes and inventory-refresh housekeeping would be noisy
  if (job.schedule_id || job.webhook_id) return false
  if (job.action === 'refresh' && job.service === 'inventory') return false
  return job.status === 'completed'
}

// Watches running jobs app-wide so cache invalidation and completion feedback
// don't depend on the user sitting on the Job Detail page.
export function useJobCompletionWatcher() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const seeded = useRef(false)
  const runningRef = useRef<Map<string, Job>>(new Map())
  const handledRef = useRef<Set<string>>(new Set())

  const { data } = useQuery({
    queryKey: ['jobs', 'watch'],
    queryFn: async () => {
      const { data } = await api.get('/api/jobs', { params: { status: 'running', lite: true } })
      return (data.jobs || []) as Job[]
    },
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })

  useEffect(() => {
    if (!data) return
    const current = new Map(data.map((j) => [j.id, j]))

    // First poll only seeds the running set — jobs that finished before mount never toast
    if (!seeded.current) {
      seeded.current = true
      runningRef.current = current
      return
    }

    for (const id of runningRef.current.keys()) {
      if (current.has(id) || handledRef.current.has(id)) continue
      handledRef.current.add(id)

      api
        .get(`/api/jobs/${id}`)
        .then(({ data: job }: { data: Job }) => {
          for (const key of INVALIDATE_KEYS) {
            queryClient.invalidateQueries({ queryKey: key })
          }
          if (!shouldToast(job)) return
          const label = `${job.action} ${job.service}`
          const action = { label: 'View job', onClick: () => navigate(`/jobs/${job.id}`) }
          if (job.status === 'failed') {
            toast.error(`${label} failed`, { action, duration: 10000 })
          } else {
            toast.success(`${label} completed`, { action })
          }
        })
        .catch(() => {})
    }

    runningRef.current = current
  }, [data, queryClient, navigate])
}
