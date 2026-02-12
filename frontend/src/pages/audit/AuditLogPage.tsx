import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { formatDate } from '@/lib/utils'
import { PageHeader } from '@/components/shared/PageHeader'
import { DataTable } from '@/components/data/DataTable'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { ColumnDef } from '@tanstack/react-table'
import type { AuditEntry } from '@/types'

export default function AuditLogPage() {
  const [page, setPage] = useState(1)
  const [actionFilter, setActionFilter] = useState('')
  const [usernameFilter, setUsernameFilter] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['audit', page, actionFilter, usernameFilter],
    queryFn: async () => {
      const params = new URLSearchParams({ page: String(page), per_page: '50' })
      if (actionFilter) params.set('action', actionFilter)
      if (usernameFilter) params.set('username', usernameFilter)
      const { data } = await api.get(`/api/audit?${params}`)
      return data as { entries: AuditEntry[]; total: number; page: number; per_page: number }
    },
  })

  const entries = data?.entries || []
  const total = data?.total || 0
  const totalPages = Math.ceil(total / 50)

  const columns = useMemo<ColumnDef<AuditEntry>[]>(
    () => [
      {
        accessorKey: 'timestamp',
        header: 'Time',
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            {formatDate(row.original.timestamp)}
          </span>
        ),
      },
      {
        accessorKey: 'username',
        header: 'User',
        cell: ({ row }) => <span className="font-medium">{row.original.username}</span>,
      },
      {
        accessorKey: 'action',
        header: 'Action',
        cell: ({ row }) => <Badge variant="outline">{row.original.action}</Badge>,
      },
      {
        accessorKey: 'resource',
        header: 'Resource',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">{row.original.resource}</span>
        ),
      },
      {
        accessorKey: 'ip_address',
        header: 'IP',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.original.ip_address || '-'}
          </span>
        ),
      },
      {
        accessorKey: 'details',
        header: 'Details',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs max-w-xs truncate block">
            {typeof row.original.details === 'object'
              ? JSON.stringify(row.original.details)
              : row.original.details || '-'}
          </span>
        ),
      },
    ],
    []
  )

  return (
    <div>
      <PageHeader title="Audit Log" description="System activity and security events" />

      <div className="flex gap-2 mb-4">
        <Input
          placeholder="Filter by action..."
          value={actionFilter}
          onChange={(e) => { setActionFilter(e.target.value); setPage(1) }}
          className="max-w-xs"
        />
        <Input
          placeholder="Filter by username..."
          value={usernameFilter}
          onChange={(e) => { setUsernameFilter(e.target.value); setPage(1) }}
          className="max-w-xs"
        />
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : (
        <>
          <DataTable columns={columns} data={entries} pageSize={50} />
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-muted-foreground">
                Page {page} of {totalPages} ({total} entries)
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
