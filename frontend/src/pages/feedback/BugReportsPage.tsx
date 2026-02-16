import { useState, useMemo } from 'react'
import { useHasPermission } from '@/lib/permissions'
import { useAllBugReports, useMyBugReports, useUpdateBugReport } from '@/hooks/useBugReports'
import { PageHeader } from '@/components/shared/PageHeader'
import { DataTable } from '@/components/data/DataTable'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import type { ColumnDef } from '@tanstack/react-table'

interface BugReport {
  id: number
  user_id: number
  username: string | null
  display_name: string | null
  title: string
  steps_to_reproduce: string
  expected_vs_actual: string
  severity: string
  page_url: string | null
  browser_info: string | null
  screenshot_path: boolean | null
  status: string
  admin_notes: string | null
  created_at: string
  updated_at: string | null
}

const severityColors: Record<string, string> = {
  critical: 'bg-red-500/15 text-red-400 border-red-500/30',
  high: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  low: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30',
}

const statusColors: Record<string, string> = {
  new: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  investigating: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  fixed: 'bg-green-500/15 text-green-400 border-green-500/30',
  'wont-fix': 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30',
  duplicate: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30',
}

const statusOptions = ['new', 'investigating', 'fixed', 'wont-fix', 'duplicate']
const severityOptions = ['low', 'medium', 'high', 'critical']

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHr = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHr / 24)

  if (diffSec < 60) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHr < 24) return `${diffHr}h ago`
  if (diffDay < 30) return `${diffDay}d ago`
  return date.toLocaleDateString()
}

function formatStatusLabel(status: string): string {
  return status
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export default function BugReportsPage() {
  const isAdmin = useHasPermission('bug_reports.view_all')
  const canManage = useHasPermission('bug_reports.manage')

  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [severityFilter, setSeverityFilter] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [selectedReport, setSelectedReport] = useState<BugReport | null>(null)
  const [editStatus, setEditStatus] = useState('')
  const [editNotes, setEditNotes] = useState('')

  const adminQuery = useAllBugReports(
    isAdmin
      ? {
          page,
          per_page: 20,
          search: search || undefined,
          status: statusFilter !== 'all' ? statusFilter : undefined,
          severity: severityFilter !== 'all' ? severityFilter : undefined,
        }
      : { enabled: false }
  )

  const userQuery = useMyBugReports(!isAdmin ? page : undefined, !isAdmin ? 20 : undefined)

  const query = isAdmin ? adminQuery : userQuery
  const reports: BugReport[] = query.data?.reports ?? []
  const total: number = query.data?.total ?? 0
  const totalPages = Math.ceil(total / 20)
  const isLoading = query.isLoading

  const updateMutation = useUpdateBugReport()

  function openDetail(report: BugReport) {
    setSelectedReport(report)
    setEditStatus(report.status)
    setEditNotes(report.admin_notes || '')
  }

  function handleSave() {
    if (!selectedReport) return
    updateMutation.mutate(
      { id: selectedReport.id, status: editStatus, admin_notes: editNotes },
      {
        onSuccess: () => {
          setSelectedReport(null)
        },
      }
    )
  }

  const columns = useMemo<ColumnDef<BugReport>[]>(() => {
    const cols: ColumnDef<BugReport>[] = [
      {
        accessorKey: 'title',
        header: 'Title',
        cell: ({ row }) => (
          <button
            className="font-medium text-left hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded"
            onClick={() => openDetail(row.original)}
          >
            {row.original.title}
          </button>
        ),
      },
    ]

    if (isAdmin) {
      cols.push({
        accessorKey: 'username',
        header: 'Submitted by',
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.display_name || row.original.username || 'Unknown'}
          </span>
        ),
      })
    }

    cols.push(
      {
        accessorKey: 'severity',
        header: 'Severity',
        cell: ({ row }) => (
          <Badge variant="outline" className={severityColors[row.original.severity] || ''}>
            {row.original.severity.charAt(0).toUpperCase() + row.original.severity.slice(1)}
          </Badge>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <Badge variant="outline" className={statusColors[row.original.status] || ''}>
            {formatStatusLabel(row.original.status)}
          </Badge>
        ),
      },
      {
        accessorKey: 'page_url',
        header: 'Page',
        enableSorting: false,
        cell: ({ row }) => {
          const url = row.original.page_url
          if (!url) return <span className="text-muted-foreground">—</span>
          const path = url.replace(/^https?:\/\/[^/]+/, '')
          const truncated = path.length > 30 ? path.slice(0, 30) + '...' : path
          return <span className="text-muted-foreground text-xs" title={url}>{truncated}</span>
        },
      },
      {
        accessorKey: 'created_at',
        header: 'Date',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">
            {formatRelativeTime(row.original.created_at)}
          </span>
        ),
      }
    )

    return cols
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin])

  return (
    <div>
      <PageHeader
        title={isAdmin ? 'Bug Reports' : 'My Bug Reports'}
        description={isAdmin ? 'View and manage all submitted bug reports' : 'View your submitted bug reports'}
      />

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(1) }}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            {statusOptions.map((s) => (
              <SelectItem key={s} value={s}>{formatStatusLabel(s)}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={severityFilter} onValueChange={(v) => { setSeverityFilter(v); setPage(1) }}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Severity" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Severities</SelectItem>
            {severityOptions.map((s) => (
              <SelectItem key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        {isAdmin && (
          <Input
            placeholder="Search by title..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
            className="max-w-sm"
          />
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <>
          <DataTable
            columns={columns}
            data={reports}
            pageSize={20}
          />

          {/* Server-side pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-muted-foreground">
                Page {page} of {totalPages} ({total} total)
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Detail Dialog */}
      <Dialog open={!!selectedReport} onOpenChange={(open) => !open && setSelectedReport(null)}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{selectedReport?.title}</DialogTitle>
            <DialogDescription>Bug report details and status information</DialogDescription>
          </DialogHeader>

          {selectedReport && (
            <div className="space-y-4">
              <div className="flex gap-2">
                <Badge variant="outline" className={severityColors[selectedReport.severity] || ''}>
                  {selectedReport.severity.charAt(0).toUpperCase() + selectedReport.severity.slice(1)}
                </Badge>
                <Badge variant="outline" className={statusColors[selectedReport.status] || ''}>
                  {formatStatusLabel(selectedReport.status)}
                </Badge>
              </div>

              {isAdmin && (
                <div>
                  <Label className="text-xs text-muted-foreground">Submitted by</Label>
                  <p className="text-sm">{selectedReport.display_name || selectedReport.username || 'Unknown'}</p>
                </div>
              )}

              <div>
                <Label className="text-xs text-muted-foreground">Steps to Reproduce</Label>
                <p className="text-sm whitespace-pre-wrap">{selectedReport.steps_to_reproduce}</p>
              </div>

              <div>
                <Label className="text-xs text-muted-foreground">Expected vs Actual</Label>
                <p className="text-sm whitespace-pre-wrap">{selectedReport.expected_vs_actual}</p>
              </div>

              {selectedReport.page_url && (
                <div>
                  <Label className="text-xs text-muted-foreground">Page URL</Label>
                  <p className="text-sm text-muted-foreground">{selectedReport.page_url}</p>
                </div>
              )}

              {selectedReport.browser_info && (
                <div>
                  <Label className="text-xs text-muted-foreground">Browser Info</Label>
                  <p className="text-xs text-muted-foreground">{selectedReport.browser_info}</p>
                </div>
              )}

              {selectedReport.screenshot_path && (
                <div>
                  <Label className="text-xs text-muted-foreground">Screenshot</Label>
                  <img
                    src={`/api/bug-reports/${selectedReport.id}/screenshot`}
                    alt="Bug report screenshot"
                    loading="lazy"
                    className="mt-1 rounded border max-w-full"
                  />
                </div>
              )}

              <div>
                <Label className="text-xs text-muted-foreground">Submitted</Label>
                <p className="text-sm">{new Date(selectedReport.created_at).toLocaleString()}</p>
              </div>

              {/* Admin controls */}
              {canManage ? (
                <div className="space-y-3 border-t pt-3">
                  <div className="space-y-2">
                    <Label>Status</Label>
                    <Select value={editStatus} onValueChange={setEditStatus}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {statusOptions.map((s) => (
                          <SelectItem key={s} value={s}>{formatStatusLabel(s)}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>Admin Notes</Label>
                    <Textarea
                      value={editNotes}
                      onChange={(e) => setEditNotes(e.target.value)}
                      placeholder="Add notes about this report..."
                      rows={3}
                    />
                  </div>
                </div>
              ) : (
                /* User read-only view of admin feedback */
                <>
                  {selectedReport.admin_notes && (
                    <div className="border-t pt-3">
                      <Label className="text-xs text-muted-foreground">Admin Notes</Label>
                      <p className="text-sm whitespace-pre-wrap">{selectedReport.admin_notes}</p>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {canManage && (
            <DialogFooter>
              <Button variant="outline" onClick={() => setSelectedReport(null)}>Cancel</Button>
              <Button onClick={handleSave} disabled={updateMutation.isPending}>
                Save Changes
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
