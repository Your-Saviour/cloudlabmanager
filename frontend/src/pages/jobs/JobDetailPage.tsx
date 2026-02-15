import { useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2, RotateCcw } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useJobStream } from '@/hooks/useJobStream'
import { formatDate } from '@/lib/utils'
import api from '@/lib/api'
import { toast } from 'sonner'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { Job } from '@/types'

export default function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const outputRef = useRef<HTMLDivElement>(null)

  const { output, status, job } = useJobStream(jobId || '')

  const rerunMutation = useMutation({
    mutationFn: () => api.post(`/api/jobs/${jobId}/rerun`),
    onSuccess: (res) => {
      toast.success('Job rerun started')
      navigate(`/jobs/${res.data.job_id}`)
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to rerun job')
    },
  })

  const isBulkJob = job?.action?.startsWith('bulk_') || !!job?.inputs?.services

  const { data: childJobs = [] } = useQuery({
    queryKey: ['jobs', jobId, 'children'],
    queryFn: async () => {
      const { data } = await api.get(`/api/jobs?parent_job_id=${jobId}`)
      return (data.jobs || []) as Job[]
    },
    enabled: !!job && isBulkJob,
    refetchInterval: status === 'running' ? 3000 : false,
  })

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [output])

  if (!jobId) return null

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="icon" onClick={() => navigate('/jobs')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl font-semibold tracking-tight">
              {job?.service || 'Job'} - {job?.action || ''}
            </h1>
            {job && <StatusBadge status={status} />}
            {job?.deployment_id && (
              <Badge variant="outline" className="text-xs font-mono">
                {job.deployment_id}
              </Badge>
            )}
            {status === 'running' && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
            {job && status !== 'running' && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => rerunMutation.mutate()}
                disabled={rerunMutation.isPending}
              >
                {rerunMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                ) : (
                  <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
                )}
                {rerunMutation.isPending ? 'Rerunning...' : 'Rerun'}
              </Button>
            )}
          </div>
          {job && (
            <p className="text-sm text-muted-foreground mt-1">
              Started {formatDate(job.started_at)}
              {job.started_by && ` by ${job.started_by}`}
              {job.finished_at && ` | Finished ${formatDate(job.finished_at)}`}
            </p>
          )}
          {job?.parent_job_id && (
            <p className="text-sm text-muted-foreground">
              Rerun of{' '}
              <button
                className="text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-sm font-mono"
                onClick={() => navigate(`/jobs/${job.parent_job_id}`)}
              >
                {job.parent_job_id}
              </button>
            </p>
          )}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Output</CardTitle>
        </CardHeader>
        <CardContent>
          {!job ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <div
              ref={outputRef}
              className="bg-black/50 rounded-md p-4 font-mono text-xs leading-relaxed overflow-auto max-h-[600px] whitespace-pre-wrap"
            >
              {output.length === 0 ? (
                <span className="text-muted-foreground">Waiting for output...</span>
              ) : (
                output.map((line, i) => (
                  <div key={i} className="text-foreground/90">
                    {line}
                  </div>
                ))
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {isBulkJob && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-sm font-medium">Child Jobs</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {childJobs.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {status === 'running' ? 'Waiting for child jobs...' : 'No child jobs found.'}
              </p>
            ) : (
              childJobs.map((child) => (
                <div key={child.id} className="flex items-center gap-3 p-2 rounded-lg bg-muted/30">
                  <StatusBadge status={child.status} />
                  <span className="text-sm font-medium">{child.service}</span>
                  <span className="text-xs text-muted-foreground">{child.action}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    onClick={() => navigate(`/jobs/${child.id}`)}
                  >
                    View
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
