import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Bookmark,
  Info,
  Pencil,
  Plus,
  X,
} from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip'
import { toast } from 'sonner'
import type { PortalBookmark } from '@/types/portal'

interface Props {
  serviceName: string
  bookmarks: PortalBookmark[]
  canEdit: boolean
}

export function BookmarkSection({ serviceName, bookmarks, canEdit }: Props) {
  const [addOpen, setAddOpen] = useState(false)
  const [editBookmark, setEditBookmark] = useState<PortalBookmark | null>(null)
  const queryClient = useQueryClient()

  const createMutation = useMutation({
    mutationFn: (body: { service_name: string; label: string; url?: string; notes?: string }) =>
      api.post('/api/portal/bookmarks', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portal-services'] })
      toast.success('Bookmark added')
      setAddOpen(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, ...body }: { id: number; label: string; url?: string; notes?: string }) =>
      api.put(`/api/portal/bookmarks/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portal-services'] })
      toast.success('Bookmark updated')
      setEditBookmark(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/portal/bookmarks/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portal-services'] })
      toast.success('Bookmark removed')
    },
  })

  return (
    <div className="border-t border-border/30 pt-3 mt-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">
          Bookmarks
        </span>
        {canEdit && (
          <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => setAddOpen(true)}>
            <Plus className="h-3 w-3 mr-1" /> Add
          </Button>
        )}
      </div>

      {bookmarks.length === 0 ? (
        <p className="text-xs text-muted-foreground">No bookmarks yet</p>
      ) : (
        <div className="space-y-1.5">
          {bookmarks.map((bm) => (
            <div key={bm.id} className="flex items-center gap-2 group text-xs">
              <Bookmark className="h-3 w-3 text-muted-foreground shrink-0" />
              {bm.url ? (
                <a
                  href={bm.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline truncate"
                >
                  {bm.label}
                </a>
              ) : (
                <span className="text-foreground truncate">{bm.label}</span>
              )}
              {bm.notes && (
                <Tooltip>
                  <TooltipTrigger>
                    <Info className="h-3 w-3 text-muted-foreground" />
                  </TooltipTrigger>
                  <TooltipContent>{bm.notes}</TooltipContent>
                </Tooltip>
              )}
              {canEdit && (
                <div className="ml-auto flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5"
                    onClick={() => setEditBookmark(bm)}
                    aria-label={`Edit bookmark ${bm.label}`}
                  >
                    <Pencil className="h-2.5 w-2.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5"
                    onClick={() => deleteMutation.mutate(bm.id)}
                    aria-label={`Delete bookmark ${bm.label}`}
                  >
                    <X className="h-2.5 w-2.5" />
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <BookmarkDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onSubmit={(values) =>
          createMutation.mutate({ service_name: serviceName, ...values })
        }
        isSubmitting={createMutation.isPending}
        title="Add Bookmark"
      />

      <BookmarkDialog
        open={!!editBookmark}
        onOpenChange={(open) => { if (!open) setEditBookmark(null) }}
        onSubmit={(values) =>
          editBookmark && updateMutation.mutate({ id: editBookmark.id, ...values })
        }
        isSubmitting={updateMutation.isPending}
        title="Edit Bookmark"
        defaultValues={editBookmark ?? undefined}
      />
    </div>
  )
}

interface BookmarkDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (values: { label: string; url?: string; notes?: string }) => void
  isSubmitting: boolean
  title: string
  defaultValues?: { label: string; url: string | null; notes: string | null }
}

function BookmarkDialog({
  open,
  onOpenChange,
  onSubmit,
  isSubmitting,
  title,
  defaultValues,
}: BookmarkDialogProps) {
  const [label, setLabel] = useState('')
  const [url, setUrl] = useState('')
  const [notes, setNotes] = useState('')

  // Reset form when dialog opens
  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) {
      setLabel(defaultValues?.label ?? '')
      setUrl(defaultValues?.url ?? '')
      setNotes(defaultValues?.notes ?? '')
    }
    onOpenChange(nextOpen)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!label.trim()) return
    onSubmit({
      label: label.trim(),
      url: url.trim() || undefined,
      notes: notes.trim() || undefined,
    })
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Save a link or note for quick access.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="bm-label">Label *</Label>
            <Input
              id="bm-label"
              placeholder="My bookmark"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="bm-url">URL</Label>
            <Input
              id="bm-url"
              type="url"
              placeholder="https://..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="bm-notes">Notes</Label>
            <Input
              id="bm-notes"
              placeholder="Optional notes..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={!label.trim() || isSubmitting}>
              {isSubmitting ? 'Saving...' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
