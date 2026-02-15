import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { relativeTime } from '@/lib/utils'
import { PageHeader } from '@/components/shared/PageHeader'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { DataTable } from '@/components/data/DataTable'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import type { ColumnDef } from '@tanstack/react-table'
import type { Job } from '@/types'

export default function JobsListPage() {
  const navigate = useNavigate()

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => {
      const { data } = await api.get('/api/jobs')
      return (data.jobs || []) as Job[]
    },
    refetchInterval: 5000,
  })

  const columns = useMemo<ColumnDef<Job>[]>(
    () => [
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: 'service',
        header: 'Service',
        cell: ({ row }) => (
          <button
            className="text-primary hover:underline font-medium"
            onClick={() => navigate(`/jobs/${row.original.id}`)}
          >
            {row.original.service}
          </button>
        ),
      },
      {
        accessorKey: 'action',
        header: 'Action',
        cell: ({ row }) => {
          const action = row.original.action
          const isBulk = action.startsWith('bulk_')
          return (
            <div className="flex items-center gap-2">
              <span>{action}</span>
              {isBulk && (
                <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                  bulk
                </Badge>
              )}
              {row.original.deployment_id && (
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-mono">
                  {row.original.deployment_id}
                </Badge>
              )}
            </div>
          )
        },
      },
      {
        accessorKey: 'started_by',
        header: 'Started By',
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.started_by || '-'}</span>
        ),
      },
      {
        accessorKey: 'started_at',
        header: 'Started',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">{relativeTime(row.original.started_at)}</span>
        ),
      },
    ],
    []
  )

  return (
    <div>
      <PageHeader title="Jobs" description="Ansible job history and live output" />
      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <DataTable columns={columns} data={jobs} searchKey="service" searchPlaceholder="Search jobs..." />
      )}
    </div>
  )
}
