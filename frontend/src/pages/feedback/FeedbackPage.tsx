import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { MessageSquare, Bug, Plus, AlertTriangle } from 'lucide-react'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { PageHeader } from '@/components/shared/PageHeader'
import { DataTable } from '@/components/data/DataTable'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { toast } from 'sonner'
import { SubmitFeedbackModal } from '@/components/feedback/SubmitFeedbackModal'
import type { ColumnDef } from '@tanstack/react-table'

interface FeedbackRequest {
  id: number
  user_id: number
  username: string | null
  display_name: string | null
  type: 'feature_request' | 'bug_report'
  title: string
  description: string
  priority: string
  status: string
  admin_notes: string | null
  has_screenshot: boolean
  created_at: string
  updated_at: string | null
}

const priorityColors: Record<string, string> = {
  high: 'bg-red-500/15 text-red-400 border-red-500/30',
  medium: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  low: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30',
}

const statusColors: Record<string, string> = {
  new: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  reviewed: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  planned: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  in_progress: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  completed: 'bg-green-500/15 text-green-400 border-green-500/30',
  declined: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30',
}

const statusOptions = ['new', 'reviewed', 'planned', 'in_progress', 'completed', 'declined']

function formatStatusLabel(status: string): string {
  return status
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

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

export default function FeedbackPage() {
  const canViewAll = useHasPermission('feedback.view_all')
  const canManage = useHasPermission('feedback.manage')

  const queryClient = useQueryClient()

  const [submitOpen, setSubmitOpen] = useState(false)
  const [submitType, setSubmitType] = useState<'feature_request' | 'bug_report'>('feature_request')
  const [detailId, setDetailId] = useState<number | null>(null)
  const [editStatus, setEditStatus] = useState('')
  const [editNotes, setEditNotes] = useState('')
  const [tab, setTab] = useState<'all' | 'mine'>('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')

  const { data, isLoading } = useQuery({
    queryKey: ['feedback', tab, typeFilter, statusFilter],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (tab === 'mine' || !canViewAll) params.set('my_requests', 'true')
      if (typeFilter !== 'all') params.set('type', typeFilter)
      if (statusFilter !== 'all') params.set('status', statusFilter)
      const { data } = await api.get(`/api/feedback?${params}`)
      return data.feedback as FeedbackRequest[]
    },
  })

  const requests = data ?? []
  const selectedRequest = detailId ? requests.find((r) => r.id === detailId) ?? null : null

  const updateMutation = useMutation({
    mutationFn: async ({ id, status, admin_notes }: { id: number; status: string; admin_notes: string }) => {
      await api.patch(`/api/feedback/${id}`, { status, admin_notes })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feedback'] })
      setDetailId(null)
      toast.success('Feedback updated')
    },
    onError: () => {
      toast.error('Failed to update feedback')
    },
  })

  function openDetail(request: FeedbackRequest) {
    setDetailId(request.id)
    setEditStatus(request.status)
    setEditNotes(request.admin_notes || '')
  }

  function handleSave() {
    if (!selectedRequest) return
    updateMutation.mutate({ id: selectedRequest.id, status: editStatus, admin_notes: editNotes })
  }

  const columns = useMemo<ColumnDef<FeedbackRequest>[]>(() => {
    const cols: ColumnDef<FeedbackRequest>[] = [
      {
        accessorKey: 'type',
        header: 'Type',
        cell: ({ row }) => {
          const isFeature = row.original.type === 'feature_request'
          return (
            <div className="flex items-center gap-1.5">
              {isFeature ? (
                <MessageSquare className="h-4 w-4 text-blue-400" />
              ) : (
                <Bug className="h-4 w-4 text-red-400" />
              )}
              <span className="text-sm">{isFeature ? 'Feature' : 'Bug'}</span>
            </div>
          )
        },
      },
      {
        accessorKey: 'title',
        header: 'Title',
        cell: ({ row }) => (
          <button
            className="font-medium text-left hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded"
            onClick={() => openDetail(row.original)}
            aria-label={`View details: ${row.original.title}`}
          >
            {row.original.title}
          </button>
        ),
      },
      {
        accessorKey: 'priority',
        header: 'Priority',
        cell: ({ row }) => (
          <Badge variant="outline" className={priorityColors[row.original.priority] || ''}>
            {row.original.priority.charAt(0).toUpperCase() + row.original.priority.slice(1)}
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
    ]

    if (canViewAll) {
      cols.push({
        accessorKey: 'username',
        header: 'Submitted By',
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.display_name || row.original.username || 'Unknown'}
          </span>
        ),
      })
    }

    cols.push({
      accessorKey: 'created_at',
      header: 'Submitted',
      cell: ({ row }) => (
        <span className="text-muted-foreground text-sm">
          {formatRelativeTime(row.original.created_at)}
        </span>
      ),
    })

    return cols
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canViewAll])

  return (
    <div>
      <PageHeader
        title="Feedback & Bug Reports"
        description="Submit feature requests, report bugs, and track their progress"
      >
        <Button
          size="sm"
          variant="outline"
          onClick={() => { setSubmitType('bug_report'); setSubmitOpen(true) }}
        >
          <Bug className="mr-2 h-4 w-4" /> Report Bug
        </Button>
        <Button
          size="sm"
          onClick={() => { setSubmitType('feature_request'); setSubmitOpen(true) }}
        >
          <Plus className="mr-2 h-4 w-4" /> Request Feature
        </Button>
      </PageHeader>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        {canViewAll && (
          <div className="flex rounded-md border border-border overflow-hidden">
            <button
              className={`px-3 py-1.5 text-sm transition-colors ${
                tab === 'all'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-transparent text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setTab('all')}
            >
              All Requests
            </button>
            <button
              className={`px-3 py-1.5 text-sm transition-colors border-l border-border ${
                tab === 'mine'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-transparent text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setTab('mine')}
            >
              My Requests
            </button>
          </div>
        )}

        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-[150px]">
            <SelectValue placeholder="Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="feature_request">Features</SelectItem>
            <SelectItem value="bug_report">Bugs</SelectItem>
          </SelectContent>
        </Select>

        <Select value={statusFilter} onValueChange={setStatusFilter}>
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
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <DataTable columns={columns} data={requests} pageSize={20} />
      )}

      {/* Submit Modal */}
      <SubmitFeedbackModal
        open={submitOpen}
        onClose={() => setSubmitOpen(false)}
        type={submitType}
      />

      {/* Detail Dialog */}
      <Dialog open={!!selectedRequest} onOpenChange={(open) => !open && setDetailId(null)}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{selectedRequest?.title}</DialogTitle>
            <DialogDescription>Feedback details and status information</DialogDescription>
          </DialogHeader>

          {selectedRequest && (
            <div className="space-y-4">
              <div className="flex gap-2 flex-wrap">
                <Badge variant="outline" className={selectedRequest.type === 'feature_request' ? 'bg-blue-500/15 text-blue-400 border-blue-500/30' : 'bg-red-500/15 text-red-400 border-red-500/30'}>
                  {selectedRequest.type === 'feature_request' ? 'Feature Request' : 'Bug Report'}
                </Badge>
                <Badge variant="outline" className={priorityColors[selectedRequest.priority] || ''}>
                  {selectedRequest.priority.charAt(0).toUpperCase() + selectedRequest.priority.slice(1)} Priority
                </Badge>
                <Badge variant="outline" className={statusColors[selectedRequest.status] || ''}>
                  {formatStatusLabel(selectedRequest.status)}
                </Badge>
              </div>

              {canViewAll && (
                <div>
                  <Label className="text-xs text-muted-foreground">Submitted by</Label>
                  <p className="text-sm">{selectedRequest.display_name || selectedRequest.username || 'Unknown'}</p>
                </div>
              )}

              <div>
                <Label className="text-xs text-muted-foreground">Submitted</Label>
                <p className="text-sm">{new Date(selectedRequest.created_at).toLocaleString()}</p>
              </div>

              <div>
                <Label className="text-xs text-muted-foreground">Description</Label>
                <p className="text-sm whitespace-pre-wrap">{selectedRequest.description}</p>
              </div>

              {selectedRequest.has_screenshot && (
                <div>
                  <Label className="text-xs text-muted-foreground">Screenshot</Label>
                  <img
                    src={`/api/feedback/${selectedRequest.id}/screenshot`}
                    alt="Feedback screenshot"
                    loading="lazy"
                    className="mt-1 rounded border max-w-full"
                  />
                </div>
              )}

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
                      placeholder="Add notes about this request..."
                      rows={3}
                    />
                  </div>
                </div>
              ) : (
                <>
                  {selectedRequest.admin_notes && (
                    <div className="border-t pt-3">
                      <Label className="text-xs text-muted-foreground">Admin Notes</Label>
                      <p className="text-sm whitespace-pre-wrap">{selectedRequest.admin_notes}</p>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {canManage && (
            <DialogFooter>
              <Button variant="outline" onClick={() => setDetailId(null)}>Cancel</Button>
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
