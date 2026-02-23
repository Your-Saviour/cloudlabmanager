import { useState, useMemo } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Folder, File, FileText, Link2, ArrowUp, RefreshCw,
  MoreHorizontal, Download, Eye, ChevronRight, Archive,
} from 'lucide-react'
import api from '@/lib/api'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from '@/components/ui/dialog'
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem,
} from '@/components/ui/dropdown-menu'
import type { RemoteFileEntry, BrowseResponse, FilePreviewResponse } from '@/types'

interface RemoteFileBrowserProps {
  serviceName: string
  hostname: string
  initialPath?: string
}

type SortField = 'name' | 'size' | 'modified'
type SortDir = 'asc' | 'desc'

const LARGE_FILE_THRESHOLD = 100 * 1024 * 1024 // 100 MB

const TEXT_EXTENSIONS = new Set([
  'txt', 'log', 'md', 'json', 'yaml', 'yml', 'xml', 'csv', 'conf', 'cfg',
  'ini', 'sh', 'bash', 'zsh', 'py', 'js', 'ts', 'tsx', 'jsx', 'html', 'css',
  'sql', 'env', 'toml', 'properties', 'service', 'timer', 'socket',
])

function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const value = bytes / Math.pow(1024, i)
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[i]}`
}

function getFileExtension(name: string): string {
  const parts = name.split('.')
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : ''
}

function isTextFile(name: string): boolean {
  return TEXT_EXTENSIONS.has(getFileExtension(name))
}

function FileIcon({ entry }: { entry: RemoteFileEntry }) {
  if (entry.type === 'directory') return <Folder className="h-4 w-4 text-blue-400 shrink-0" />
  if (entry.type === 'symlink') return <Link2 className="h-4 w-4 text-purple-400 shrink-0" />
  if (isTextFile(entry.name)) return <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
  return <File className="h-4 w-4 text-muted-foreground shrink-0" />
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-AU', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return dateStr
  }
}

export default function RemoteFileBrowser({ serviceName, hostname, initialPath = '/' }: RemoteFileBrowserProps) {
  const [currentPath, setCurrentPath] = useState(initialPath)
  const [pathInput, setPathInput] = useState(initialPath)
  const [sortField, setSortField] = useState<SortField>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [previewFile, setPreviewFile] = useState<string | null>(null)
  const [largeFileConfirm, setLargeFileConfirm] = useState<{ entry: RemoteFileEntry; destination: string } | null>(null)

  const browseQuery = useQuery({
    queryKey: ['browse-files', serviceName, hostname, currentPath],
    queryFn: async () => {
      const { data } = await api.post<BrowseResponse>(`/api/services/${serviceName}/browse-files`, {
        hostname,
        path: currentPath,
      })
      return data
    },
  })

  const previewQuery = useQuery({
    queryKey: ['file-preview', serviceName, hostname, previewFile],
    queryFn: async () => {
      const { data } = await api.post<FilePreviewResponse>(`/api/services/${serviceName}/file-preview`, {
        hostname,
        path: previewFile,
        lines: 200,
      })
      return data
    },
    enabled: !!previewFile,
  })

  const downloadMutation = useMutation({
    mutationFn: ({ remotePath, destination }: { remotePath: string; destination: string }) =>
      api.post('/api/services/download-file/run', {
        script: 'download',
        inputs: {
          target_service: serviceName,
          remote_path: remotePath,
          destination,
        },
      }),
    onSuccess: (res) => {
      if (res.data.job_id) {
        toast.success(`Download started (Job: ${res.data.job_id.slice(0, 8)}...)`)
      } else {
        toast.success('Download started')
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Download failed'),
  })

  const sortedEntries = useMemo(() => {
    if (!browseQuery.data?.entries) return []
    const entries = [...browseQuery.data.entries]

    entries.sort((a, b) => {
      // Directories always first
      if (a.type === 'directory' && b.type !== 'directory') return -1
      if (a.type !== 'directory' && b.type === 'directory') return 1

      let cmp = 0
      switch (sortField) {
        case 'name':
          cmp = a.name.localeCompare(b.name)
          break
        case 'size':
          cmp = a.size - b.size
          break
        case 'modified':
          cmp = new Date(a.modified).getTime() - new Date(b.modified).getTime()
          break
      }
      return sortDir === 'asc' ? cmp : -cmp
    })

    return entries
  }, [browseQuery.data?.entries, sortField, sortDir])

  const navigateTo = (path: string) => {
    setCurrentPath(path)
    setPathInput(path)
  }

  const navigateUp = () => {
    if (currentPath === '/') return
    const parts = currentPath.replace(/\/$/, '').split('/')
    parts.pop()
    navigateTo(parts.length <= 1 ? '/' : parts.join('/'))
  }

  const navigateToEntry = (entry: RemoteFileEntry) => {
    if (entry.type !== 'directory') return
    const newPath = currentPath === '/' ? `/${entry.name}` : `${currentPath}/${entry.name}`
    navigateTo(newPath)
  }

  const handlePathSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = pathInput.trim()
    if (trimmed) navigateTo(trimmed.startsWith('/') ? trimmed : `/${trimmed}`)
  }

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDir('asc')
    }
  }

  const sortIndicator = (field: SortField) => {
    if (sortField !== field) return null
    return <span className="ml-1 text-xs">{sortDir === 'asc' ? '▲' : '▼'}</span>
  }

  // Build breadcrumb segments
  const breadcrumbs = useMemo(() => {
    const parts = currentPath.split('/').filter(Boolean)
    const crumbs = [{ label: '/', path: '/' }]
    let accumulated = ''
    for (const part of parts) {
      accumulated += `/${part}`
      crumbs.push({ label: part, path: accumulated })
    }
    return crumbs
  }, [currentPath])

  const handleDownload = (entry: RemoteFileEntry, destination: string) => {
    if (entry.size > LARGE_FILE_THRESHOLD) {
      setLargeFileConfirm({ entry, destination })
      return
    }
    const filePath = currentPath === '/' ? `/${entry.name}` : `${currentPath}/${entry.name}`
    downloadMutation.mutate({ remotePath: filePath, destination })
  }

  const confirmLargeDownload = () => {
    if (!largeFileConfirm) return
    const { entry, destination } = largeFileConfirm
    const filePath = currentPath === '/' ? `/${entry.name}` : `${currentPath}/${entry.name}`
    downloadMutation.mutate({ remotePath: filePath, destination })
    setLargeFileConfirm(null)
  }

  const handlePreview = (entry: RemoteFileEntry) => {
    const filePath = currentPath === '/' ? `/${entry.name}` : `${currentPath}/${entry.name}`
    setPreviewFile(filePath)
  }

  return (
    <div className="space-y-3">
      {/* Breadcrumb + path input bar */}
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={navigateUp}
          disabled={currentPath === '/'}
          aria-label="Navigate to parent directory"
        >
          <ArrowUp className="h-4 w-4" />
        </Button>

        <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm text-muted-foreground overflow-x-auto shrink min-w-0">
          {breadcrumbs.map((crumb, i) => (
            <span key={crumb.path} className="flex items-center gap-1 whitespace-nowrap">
              {i > 0 && <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground/50" />}
              <button
                className="hover:text-foreground transition-colors"
                onClick={() => navigateTo(crumb.path)}
              >
                {crumb.label}
              </button>
            </span>
          ))}
        </nav>

        <form onSubmit={handlePathSubmit} className="flex items-center gap-1 ml-auto shrink-0">
          <Input
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            className="h-8 w-48 font-mono text-xs"
            placeholder="/path/to/dir"
          />
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => browseQuery.refetch()}
            disabled={browseQuery.isFetching}
            aria-label="Refresh directory listing"
          >
            <RefreshCw className={`h-4 w-4 ${browseQuery.isFetching ? 'animate-spin' : ''}`} />
          </Button>
        </form>
      </div>

      {/* File table */}
      <Card>
        <CardContent className="p-0">
          {/* Column headers */}
          <div className="grid grid-cols-[1fr_80px_110px_70px_100px_36px] gap-2 px-3 py-2 border-b text-xs font-medium text-muted-foreground">
            <button className="text-left flex items-center" onClick={() => toggleSort('name')}>
              Name{sortIndicator('name')}
            </button>
            <button className="text-right flex items-center justify-end" onClick={() => toggleSort('size')}>
              Size{sortIndicator('size')}
            </button>
            <span className="text-left">Perms</span>
            <span className="text-left">Owner</span>
            <button className="text-left flex items-center" onClick={() => toggleSort('modified')}>
              Modified{sortIndicator('modified')}
            </button>
            <span></span>
          </div>

          {/* Loading state */}
          {browseQuery.isLoading && (
            <div className="space-y-0">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="grid grid-cols-[1fr_80px_110px_70px_100px_36px] gap-2 px-3 py-2.5 border-b last:border-0">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-4 w-12 ml-auto" />
                  <Skeleton className="h-4 w-20" />
                  <Skeleton className="h-4 w-10" />
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-4 w-6" />
                </div>
              ))}
            </div>
          )}

          {/* Error state */}
          {browseQuery.isError && (
            <div className="px-3 py-8 text-center">
              <p className="text-sm text-destructive">
                {(browseQuery.error as any)?.response?.data?.detail || 'Failed to browse directory'}
              </p>
              <Button variant="ghost" size="sm" className="mt-2" onClick={() => browseQuery.refetch()}>
                Retry
              </Button>
            </div>
          )}

          {/* Empty state */}
          {browseQuery.data && sortedEntries.length === 0 && (
            <div className="px-3 py-8 text-center">
              <Folder className="mx-auto h-8 w-8 text-muted-foreground/30 mb-2" />
              <p className="text-sm text-muted-foreground">Empty directory</p>
            </div>
          )}

          {/* File entries */}
          {sortedEntries.map((entry) => (
            <div
              key={entry.name}
              className="grid grid-cols-[1fr_80px_110px_70px_100px_36px] gap-2 px-3 py-2 border-b last:border-0 hover:bg-muted/50 transition-colors group"
              onDoubleClick={() => navigateToEntry(entry)}
            >
              {/* Name */}
              <div className="flex items-center gap-2 min-w-0">
                <FileIcon entry={entry} />
                {entry.type === 'directory' ? (
                  <button
                    className="truncate text-sm hover:text-primary transition-colors text-left"
                    onClick={() => navigateToEntry(entry)}
                  >
                    {entry.name}/
                  </button>
                ) : (
                  <span className="truncate text-sm">
                    {entry.name}
                    {entry.type === 'symlink' && entry.link_target && (
                      <span className="text-muted-foreground/60 ml-1">→ {entry.link_target}</span>
                    )}
                  </span>
                )}
              </div>

              {/* Size */}
              <span className="text-right font-mono text-xs text-muted-foreground self-center">
                {entry.type === 'directory' ? '—' : formatSize(entry.size)}
              </span>

              {/* Permissions */}
              <span className="font-mono text-xs text-muted-foreground self-center">
                {entry.permissions}
              </span>

              {/* Owner */}
              <span className="text-xs text-muted-foreground self-center truncate">
                {entry.owner}
              </span>

              {/* Modified */}
              <span className="text-xs text-muted-foreground self-center">
                {formatDate(entry.modified)}
              </span>

              {/* Actions */}
              <div className="self-center">
                {entry.type !== 'directory' && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <MoreHorizontal className="h-4 w-4" />
                        <span className="sr-only">File actions for {entry.name}</span>
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => handleDownload(entry, 'file_library')}>
                        <Archive className="h-4 w-4 mr-2" />
                        Download to Library
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => handleDownload(entry, 'direct_download')}>
                        <Download className="h-4 w-4 mr-2" />
                        Direct Download
                      </DropdownMenuItem>
                      {isTextFile(entry.name) && (
                        <DropdownMenuItem onClick={() => handlePreview(entry)}>
                          <Eye className="h-4 w-4 mr-2" />
                          View Contents
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Cache indicator */}
      {browseQuery.data?.cached && (
        <div className="text-xs text-muted-foreground flex items-center gap-1">
          <span>Cached result</span>
          <span>·</span>
          <button
            className="hover:text-foreground transition-colors underline"
            onClick={() => browseQuery.refetch()}
          >
            Refresh
          </button>
        </div>
      )}

      {/* Large file confirmation */}
      <ConfirmDialog
        open={!!largeFileConfirm}
        onOpenChange={() => setLargeFileConfirm(null)}
        title="Large File Download"
        description={largeFileConfirm ? `This file is ${formatSize(largeFileConfirm.entry.size)}. Large downloads may take several minutes. Continue?` : ''}
        confirmLabel="Download"
        onConfirm={confirmLargeDownload}
      />

      {/* Preview dialog */}
      <Dialog open={!!previewFile} onOpenChange={(open) => !open && setPreviewFile(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{previewFile}</DialogTitle>
            <DialogDescription>
              {previewQuery.data && (
                <span className="text-xs">
                  {formatSize(previewQuery.data.size)} · {previewQuery.data.mime_type}
                  {previewQuery.data.lines_returned && ` · ${previewQuery.data.lines_returned} lines`}
                </span>
              )}
            </DialogDescription>
          </DialogHeader>

          {previewQuery.isLoading && (
            <div className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          )}

          {previewQuery.isError && (
            <p className="text-sm text-destructive">
              {(previewQuery.error as any)?.response?.data?.detail || 'Failed to load preview'}
            </p>
          )}

          {previewQuery.data && (
            previewQuery.data.is_binary ? (
              <div className="text-center py-8">
                <Badge variant="secondary" className="mb-3">{previewQuery.data.mime_type}</Badge>
                <p className="text-sm text-muted-foreground">Binary file — download only</p>
              </div>
            ) : (
              <pre className="bg-black/30 rounded-md p-3 text-xs font-mono whitespace-pre-wrap break-all overflow-x-auto">
                {previewQuery.data.content}
              </pre>
            )
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
