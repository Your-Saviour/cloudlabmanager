import { useState, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { formatDate } from '@/lib/utils'
import { PageHeader } from '@/components/shared/PageHeader'
import { DataTable } from '@/components/data/DataTable'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Label } from '@/components/ui/label'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Download, X } from 'lucide-react'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import type { AuditEntry, AuditFilters, AuditListResponse } from '@/types'

interface AuditFilterState {
  username: string
  actionPrefix: string
  dateFrom: string
  dateTo: string
  search: string
}

export default function AuditLogPage() {
  const [filters, setFilters] = useState<AuditFilterState>({
    username: '', actionPrefix: '', dateFrom: '', dateTo: '', search: '',
  })
  const [searchInput, setSearchInput] = useState('')
  const [cursor, setCursor] = useState<number | null>(null)
  const [cursorStack, setCursorStack] = useState<number[]>([])

  useEffect(() => {
    const timer = setTimeout(() => {
      setFilters(prev => ({ ...prev, search: searchInput }))
      setCursor(null)
      setCursorStack([])
    }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  const { data: filterOptions } = useQuery({
    queryKey: ['audit-filters'],
    queryFn: async () => {
      const { data } = await api.get('/api/audit/filters')
      return data as AuditFilters
    },
    staleTime: 60000,
  })

  const { data, isLoading } = useQuery({
    queryKey: ['audit', filters, cursor],
    queryFn: async () => {
      const params = new URLSearchParams({ per_page: '50' })
      if (cursor) params.set('cursor', String(cursor))
      if (filters.username) params.set('username', filters.username)
      if (filters.actionPrefix) params.set('action_prefix', filters.actionPrefix)
      if (filters.dateFrom) params.set('date_from', filters.dateFrom)
      if (filters.dateTo) params.set('date_to', filters.dateTo)
      if (filters.search) params.set('search', filters.search)
      const { data } = await api.get(`/api/audit?${params}`)
      return data as AuditListResponse
    },
  })

  const entries = data?.entries || []
  const total = data?.total || 0

  const updateFilter = (key: keyof AuditFilterState, value: string) => {
    if (key === 'search') return
    setFilters(prev => ({ ...prev, [key]: value }))
    setCursor(null)
    setCursorStack([])
  }

  const clearFilters = () => {
    setFilters({ username: '', actionPrefix: '', dateFrom: '', dateTo: '', search: '' })
    setSearchInput('')
    setCursor(null)
    setCursorStack([])
  }

  const hasActiveFilters = filters.username !== '' || filters.actionPrefix !== '' ||
    filters.dateFrom !== '' || filters.dateTo !== '' || searchInput !== ''

  const handleExport = async (format: 'csv' | 'json') => {
    const params = new URLSearchParams({ format })
    if (filters.username) params.set('username', filters.username)
    if (filters.actionPrefix) params.set('action_prefix', filters.actionPrefix)
    if (filters.dateFrom) params.set('date_from', filters.dateFrom)
    if (filters.dateTo) params.set('date_to', filters.dateTo)
    if (filters.search) params.set('search', filters.search)

    try {
      const response = await api.get(`/api/audit/export?${params}`, {
        responseType: 'blob',
      })

      const contentDisposition = response.headers['content-disposition']
      const filenameMatch = contentDisposition?.match(/filename=(.+)/)
      const filename = filenameMatch?.[1] || `audit_log.${format}`

      const url = window.URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)

      toast.success(`Exported audit log as ${format.toUpperCase()}`)
    } catch {
      toast.error('Failed to export audit log')
    }
  }

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

      <div className="flex flex-wrap gap-x-3 gap-y-2 mb-4 items-end" role="search" aria-label="Audit log filters">
        <div className="space-y-1">
          <Label htmlFor="audit-user-filter" className="text-xs text-muted-foreground">User</Label>
          <Select value={filters.username || '__all__'} onValueChange={(v) => updateFilter('username', v === '__all__' ? '' : v)}>
            <SelectTrigger id="audit-user-filter" className="w-[160px]">
              <SelectValue placeholder="All users" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">All users</SelectItem>
              {filterOptions?.usernames.map(u => (
                <SelectItem key={u} value={u}>{u}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <Label htmlFor="audit-category-filter" className="text-xs text-muted-foreground">Category</Label>
          <Select value={filters.actionPrefix || '__all__'} onValueChange={(v) => updateFilter('actionPrefix', v === '__all__' ? '' : v)}>
            <SelectTrigger id="audit-category-filter" className="w-[160px]">
              <SelectValue placeholder="All categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">All categories</SelectItem>
              {filterOptions?.action_categories.map(c => (
                <SelectItem key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <Label htmlFor="audit-date-from" className="text-xs text-muted-foreground">From</Label>
          <Input
            id="audit-date-from"
            type="datetime-local"
            value={filters.dateFrom ? filters.dateFrom.slice(0, 16) : ''}
            onChange={(e) => updateFilter('dateFrom', e.target.value ? new Date(e.target.value).toISOString() : '')}
            className="w-[200px]"
          />
        </div>

        <div className="space-y-1">
          <Label htmlFor="audit-date-to" className="text-xs text-muted-foreground">To</Label>
          <Input
            id="audit-date-to"
            type="datetime-local"
            value={filters.dateTo ? filters.dateTo.slice(0, 16) : ''}
            onChange={(e) => updateFilter('dateTo', e.target.value ? new Date(e.target.value).toISOString() : '')}
            className="w-[200px]"
          />
        </div>

        <div className="space-y-1 flex-1 min-w-[200px]">
          <Label htmlFor="audit-search" className="text-xs text-muted-foreground">Search</Label>
          <Input
            id="audit-search"
            type="text"
            placeholder="Search actions, resources, details..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-2 self-end">
          {hasActiveFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters} aria-label="Clear all filters">
              <X className="h-4 w-4 mr-1" /> Clear
            </Button>
          )}

          {data?.total != null && data.total > 0 && (
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              {data.total.toLocaleString()} entries
            </span>
          )}

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" aria-label="Export audit log">
                <Download className="h-4 w-4 mr-1" /> Export
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => handleExport('csv')}>
                Export as CSV
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleExport('json')}>
                Export as JSON
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : (
        <>
          <DataTable columns={columns} data={entries} pageSize={50} />
          <nav className="flex items-center justify-between mt-4" aria-label="Audit log pagination">
            <p className="text-sm text-muted-foreground" aria-live="polite">
              {total ? `${total.toLocaleString()} entries` : 'No entries'}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={cursorStack.length === 0}
                onClick={() => {
                  const newStack = [...cursorStack]
                  const prevCursor = newStack.pop()
                  setCursorStack(newStack)
                  setCursor(prevCursor === -1 ? null : prevCursor ?? null)
                }}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!data?.next_cursor}
                onClick={() => {
                  setCursorStack(prev => [...prev, cursor ?? -1])
                  setCursor(data!.next_cursor)
                }}
              >
                Next
              </Button>
            </div>
          </nav>
        </>
      )}
    </div>
  )
}
