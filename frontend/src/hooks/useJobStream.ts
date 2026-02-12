import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { Job } from '@/types'

export function useJobStream(jobId: string) {
  const [output, setOutput] = useState<string[]>([])
  const [status, setStatus] = useState<Job['status']>('running')
  const intervalRef = useRef<ReturnType<typeof setInterval>>()

  const { data: job } = useQuery({
    queryKey: ['job', jobId],
    queryFn: async () => {
      const { data } = await api.get(`/api/jobs/${jobId}`)
      return data as Job
    },
  })

  useEffect(() => {
    if (!job) return
    setOutput(job.output || [])
    setStatus(job.status)

    if (job.status === 'running') {
      intervalRef.current = setInterval(async () => {
        try {
          const { data } = await api.get(`/api/jobs/${jobId}`)
          setOutput(data.output || [])
          setStatus(data.status)
          if (data.status !== 'running') {
            clearInterval(intervalRef.current)
          }
        } catch {
          clearInterval(intervalRef.current)
        }
      }, 1000)
    }

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [job?.id])

  return { output, status, job }
}
