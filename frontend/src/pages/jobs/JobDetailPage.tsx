import { useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { useJobStream } from '@/hooks/useJobStream'
import { formatDate } from '@/lib/utils'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export default function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const outputRef = useRef<HTMLDivElement>(null)

  const { output, status, job } = useJobStream(jobId || '')

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
          <div className="flex items-center gap-3">
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
          </div>
          {job && (
            <p className="text-sm text-muted-foreground mt-1">
              Started {formatDate(job.started_at)}
              {job.started_by && ` by ${job.started_by}`}
              {job.finished_at && ` | Finished ${formatDate(job.finished_at)}`}
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
    </div>
  )
}
