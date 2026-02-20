import { useState, useMemo, useCallback, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  MoreHorizontal,
  Pencil,
  Trash,
  Download,
  Upload,
  FileIcon,
} from 'lucide-react'
import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { relativeTime } from '@/lib/utils'
import { PageHeader } from '@/components/shared/PageHeader'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { DataTable } from '@/components/data/DataTable'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import type { FileLibraryItem } from '@/types'

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function FileLibraryPage() {
  const queryClient = useQueryClient()

  const canUpload = useHasPermission('files.upload')
  const canEdit = useHasPermission('files.edit')
  const canDelete = useHasPermission('files.delete')

  // Dialog state
  const [uploadOpen, setUploadOpen] = useState(false)
  const [editItem, setEditItem] = useState<FileLibraryItem | null>(null)
  const [deleteItem, setDeleteItem] = useState<FileLibraryItem | null>(null)

  // Upload form state
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadDescription, setUploadDescription] = useState('')
  const [uploadTags, setUploadTags] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Edit form state
  const [editDescription, setEditDescription] = useState('')
  const [editTags, setEditTags] = useState('')

  // Data fetching
  const { data: files = [], isLoading } = useQuery({
    queryKey: ['file-library'],
    queryFn: async () => {
      const { data } = await api.get('/api/files')
      return (data.files || data || []) as FileLibraryItem[]
    },
  })

  const { data: stats } = useQuery({
    queryKey: ['file-library-stats'],
    queryFn: async () => {
      const { data } = await api.get('/api/files/stats')
      return data as {
        total_size_bytes: number
        file_count: number
        quota_mb: number
        used_percent: number
      }
    },
  })

  // Upload mutation
  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData()
      formData.append('file', file)
      if (uploadDescription.trim()) {
        formData.append('description', uploadDescription.trim())
      }
      if (uploadTags.trim()) {
        const tags = uploadTags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean)
        formData.append('tags', JSON.stringify(tags))
      }
      return api.post('/api/files', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['file-library'] })
      queryClient.invalidateQueries({ queryKey: ['file-library-stats'] })
      closeUploadDialog()
      toast.success('File uploaded')
    },
    onError: (err: any) =>
      toast.error(err.response?.data?.detail || 'Upload failed'),
  })

  // Edit mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { description: string | null; tags: string[] } }) =>
      api.put(`/api/files/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['file-library'] })
      setEditItem(null)
      toast.success('File updated')
    },
    onError: (err: any) =>
      toast.error(err.response?.data?.detail || 'Update failed'),
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/files/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['file-library'] })
      queryClient.invalidateQueries({ queryKey: ['file-library-stats'] })
      setDeleteItem(null)
      toast.success('File deleted')
    },
    onError: () => toast.error('Delete failed'),
  })

  const closeUploadDialog = useCallback(() => {
    setUploadOpen(false)
    setUploadFile(null)
    setUploadDescription('')
    setUploadTags('')
    setIsDragging(false)
  }, [])

  const openEditDialog = useCallback((item: FileLibraryItem) => {
    setEditItem(item)
    setEditDescription(item.description || '')
    setEditTags(item.tags?.join(', ') || '')
  }, [])

  const handleDownload = useCallback(async (item: FileLibraryItem) => {
    try {
      const { data } = await api.get(`/api/files/${item.id}/download`, {
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(new Blob([data]))
      const a = document.createElement('a')
      a.href = url
      a.download = item.original_name
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      toast.error('Download failed')
    }
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const droppedFile = e.dataTransfer.files[0]
    if (droppedFile) setUploadFile(droppedFile)
  }, [])

  // Check if a date is stale (30+ days ago)
  const isStale = useCallback((dateStr: string | null) => {
    if (!dateStr) return false
    const date = new Date(dateStr)
    const thirtyDaysAgo = new Date()
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30)
    return date < thirtyDaysAgo
  }, [])

  const columns = useMemo<ColumnDef<FileLibraryItem>[]>(
    () => [
      {
        accessorKey: 'original_name',
        header: 'File Name',
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <FileIcon className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="font-medium truncate max-w-[200px]">
              {row.original.original_name}
            </span>
            {row.original.mime_type && (
              <Badge variant="outline" className="text-[10px] shrink-0">
                {row.original.mime_type.split('/').pop()}
              </Badge>
            )}
          </div>
        ),
      },
      {
        accessorKey: 'size_bytes',
        header: 'Size',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">
            {formatFileSize(row.original.size_bytes)}
          </span>
        ),
      },
      {
        accessorKey: 'username',
        header: 'Uploaded By',
        cell: ({ row }) => (
          <span className="text-xs">{row.original.username}</span>
        ),
      },
      {
        accessorKey: 'uploaded_at',
        header: 'Date',
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">
            {relativeTime(row.original.uploaded_at)}
          </span>
        ),
      },
      {
        accessorKey: 'description',
        header: 'Description',
        cell: ({ row }) => {
          const desc = row.original.description
          if (!desc) return <span className="text-muted-foreground text-xs">—</span>
          if (desc.length <= 40) {
            return <span className="text-xs">{desc}</span>
          }
          return (
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild>
                <span className="text-xs truncate max-w-[150px] block cursor-default">
                  {desc.slice(0, 40)}…
                </span>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-[300px]">
                {desc}
              </TooltipContent>
            </Tooltip>
          )
        },
      },
      {
        accessorKey: 'tags',
        header: 'Tags',
        cell: ({ row }) => {
          const tags = row.original.tags
          if (!tags || tags.length === 0) return null
          return (
            <div className="flex gap-1 flex-wrap">
              {tags.map((tag) => (
                <Badge key={tag} variant="secondary" className="text-[10px]">
                  {tag}
                </Badge>
              ))}
            </div>
          )
        },
      },
      {
        accessorKey: 'last_used_at',
        header: 'Last Used',
        cell: ({ row }) => {
          const lastUsed = row.original.last_used_at
          if (!lastUsed) {
            return <span className="text-muted-foreground/60 text-xs italic">Never</span>
          }
          const stale = isStale(lastUsed)
          return (
            <span className={`text-xs ${stale ? 'text-yellow-600 dark:text-yellow-500' : 'text-muted-foreground'}`}>
              {relativeTime(lastUsed)}
            </span>
          )
        },
      },
      {
        id: 'actions',
        cell: ({ row }) => (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7">
                <MoreHorizontal className="h-4 w-4" />
                <span className="sr-only">Actions</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => handleDownload(row.original)}>
                <Download className="mr-2 h-3 w-3" /> Download
              </DropdownMenuItem>
              {canEdit && (
                <DropdownMenuItem onClick={() => openEditDialog(row.original)}>
                  <Pencil className="mr-2 h-3 w-3" /> Edit
                </DropdownMenuItem>
              )}
              {canDelete && (
                <DropdownMenuItem
                  className="text-destructive"
                  onClick={() => setDeleteItem(row.original)}
                >
                  <Trash className="mr-2 h-3 w-3" /> Delete
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    [canEdit, canDelete, openEditDialog, handleDownload, isStale]
  )

  return (
    <div>
      <PageHeader
        title="File Library"
        description="Upload and manage reusable files"
      >
        {canUpload && (
          <Button size="sm" onClick={() => setUploadOpen(true)}>
            <Plus className="mr-2 h-4 w-4" /> Upload File
          </Button>
        )}
      </PageHeader>

      {stats && (
        <div className="mb-4 p-3 rounded-lg border bg-card">
          <div className="flex items-center justify-between text-sm mb-1">
            <span className="text-muted-foreground">
              Storage: {(stats.total_size_bytes / (1024 * 1024)).toFixed(1)} MB / {stats.quota_mb} MB
              ({stats.file_count} files)
            </span>
            <span className="text-muted-foreground">{stats.used_percent}% used</span>
          </div>
          <div
            role="progressbar"
            aria-valuenow={stats.used_percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Storage usage: ${stats.used_percent}% of ${stats.quota_mb} MB`}
            className="h-2 rounded-full bg-muted overflow-hidden"
          >
            <div
              className={`h-full rounded-full transition-all ${
                stats.used_percent > 90
                  ? 'bg-destructive'
                  : stats.used_percent > 70
                    ? 'bg-yellow-500'
                    : 'bg-primary'
              }`}
              style={{ width: `${Math.min(stats.used_percent, 100)}%` }}
            />
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={files}
          searchKey="original_name"
          searchPlaceholder="Search files..."
        />
      )}

      {/* Upload Dialog */}
      <Dialog open={uploadOpen} onOpenChange={(open) => !open && closeUploadDialog()}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Upload File</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {/* Drag-and-drop zone */}
            <div
              role="button"
              tabIndex={0}
              aria-label="Drop a file here or click to browse"
              className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
                isDragging
                  ? 'border-primary bg-primary/5'
                  : 'border-muted-foreground/25 hover:border-muted-foreground/50'
              }`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInputRef.current?.click() } }}
            >
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) setUploadFile(f)
                }}
              />
              <Upload className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
              {uploadFile ? (
                <div>
                  <p className="text-sm font-medium">{uploadFile.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatFileSize(uploadFile.size)}
                  </p>
                </div>
              ) : (
                <div>
                  <p className="text-sm text-muted-foreground">
                    Drag and drop a file here, or click to browse
                  </p>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label>Description (optional)</Label>
              <Textarea
                value={uploadDescription}
                onChange={(e) => setUploadDescription(e.target.value)}
                placeholder="What is this file for?"
                rows={2}
              />
            </div>

            <div className="space-y-2">
              <Label>Tags (optional)</Label>
              <Input
                value={uploadTags}
                onChange={(e) => setUploadTags(e.target.value)}
                placeholder="e.g. config, certificate, script"
              />
              <p className="text-[10px] text-muted-foreground">
                Comma-separated list of tags
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeUploadDialog}>
              Cancel
            </Button>
            <Button
              onClick={() => uploadFile && uploadMutation.mutate(uploadFile)}
              disabled={!uploadFile || uploadMutation.isPending}
            >
              {uploadMutation.isPending ? 'Uploading...' : 'Upload'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editItem} onOpenChange={() => setEditItem(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Edit — {editItem?.original_name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                placeholder="File description"
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label>Tags</Label>
              <Input
                value={editTags}
                onChange={(e) => setEditTags(e.target.value)}
                placeholder="e.g. config, certificate, script"
              />
              <p className="text-[10px] text-muted-foreground">
                Comma-separated list of tags
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditItem(null)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                editItem &&
                updateMutation.mutate({
                  id: editItem.id,
                  body: {
                    description: editDescription.trim() || null,
                    tags: editTags
                      .split(',')
                      .map((t) => t.trim())
                      .filter(Boolean),
                  },
                })
              }
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? 'Saving...' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <ConfirmDialog
        open={!!deleteItem}
        onOpenChange={() => setDeleteItem(null)}
        title="Delete File"
        description={`Are you sure you want to delete "${deleteItem?.original_name}"?`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteItem && deleteMutation.mutate(deleteItem.id)}
      />
    </div>
  )
}
