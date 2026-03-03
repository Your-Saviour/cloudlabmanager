import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Clock } from 'lucide-react'
import api from '@/lib/api'
import { relativeTime } from '@/lib/utils'
import { Card, CardContent } from '@/components/ui/card'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Skeleton } from '@/components/ui/skeleton'
import type { Job } from '@/types'

export function RecentJobsWidget(_props: { config: Record<string, any> }) {
  const navigate = useNavigate()

  const { data: jobs, isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => {
      const { data } = await api.get('/api/jobs')
      return (data.jobs || []) as Job[]
    },
    refetchInterval: 5000,
  })

  const recentJobs = jobs?.slice(0, 5) || []

  return (
    <Card>
      <CardContent className="pt-6">
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : recentJobs.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">No jobs yet</p>
        ) : (
          <div className="space-y-2">
            {recentJobs.map((job) => (
              <button
                key={job.id}
                className="flex items-center justify-between w-full rounded-md px-3 py-2 text-sm hover:bg-muted/50 transition-colors text-left"
                onClick={() => navigate(`/jobs/${job.id}`)}
              >
                <div className="flex items-center gap-3">
                  <StatusBadge status={job.status} />
                  <span className="font-medium">{job.service}</span>
                  <span className="text-muted-foreground">{job.action}</span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  <span className="text-xs">{relativeTime(job.started_at)}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
