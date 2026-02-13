import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Clock, RotateCcw, GitCompare } from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { toast } from 'sonner'
import ConfigDiffViewer from './ConfigDiffViewer'

interface ConfigVersionHistoryProps {
  serviceName: string
  filename: string
  onRestore: () => void
}

interface ConfigVersion {
  id: number
  version_number: number
  content_hash: string
  size_bytes: number
  change_note: string | null
  created_by_username: string | null
  created_at: string | null
}

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(dateStr).toLocaleDateString()
}

export default function ConfigVersionHistory({ serviceName, filename, onRestore }: ConfigVersionHistoryProps) {
  const queryClient = useQueryClient()
  const [viewingDiffId, setViewingDiffId] = useState<number | null>(null)
  const [restoreTarget, setRestoreTarget] = useState<ConfigVersion | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['service', serviceName, 'config', filename, 'versions'],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${serviceName}/configs/${filename}/versions`)
      return data.versions as ConfigVersion[]
    },
  })

  const restoreMutation = useMutation({
    mutationFn: (version: ConfigVersion) =>
      api.post(`/api/services/${serviceName}/configs/${filename}/versions/${version.id}/restore`, {
        change_note: `Restored from version ${version.version_number}`,
      }),
    onSuccess: (_, version) => {
      toast.success(`Restored to version ${version.version_number}`)
      queryClient.invalidateQueries({ queryKey: ['service', serviceName, 'config', filename] })
      queryClient.invalidateQueries({ queryKey: ['service', serviceName, 'config', filename, 'versions'] })
      setRestoreTarget(null)
      onRestore()
    },
    onError: () => {
      toast.error('Restore failed')
      setRestoreTarget(null)
    },
  })

  const versions = data || []

  if (isLoading) {
    return <Skeleton className="h-48 w-full" />
  }

  if (versions.length === 0) {
    return (
      <div className="text-center py-8">
        <Clock className="mx-auto h-8 w-8 text-muted-foreground/50 mb-2" />
        <p className="text-sm text-muted-foreground">No version history yet.</p>
        <p className="text-xs text-muted-foreground/70 mt-1">Versions are created when you save changes.</p>
      </div>
    )
  }

  return (
    <>
      <ScrollArea className="h-[500px]">
        <div className="space-y-3 pr-4">
          {versions.map((version, index) => (
            <div
              key={version.id}
              className="border border-border rounded-md p-3 hover:border-primary/30 transition-colors"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono text-sm font-medium">v{version.version_number}</span>
                {index === 0 && <Badge variant="success" className="text-[10px] px-1.5 py-0">Current</Badge>}
                <span className="text-xs text-muted-foreground">
                  {version.created_at ? timeAgo(version.created_at) : 'unknown'}
                </span>
                {version.created_by_username && (
                  <>
                    <span className="text-xs text-muted-foreground/50">&middot;</span>
                    <span className="text-xs text-muted-foreground">{version.created_by_username}</span>
                  </>
                )}
              </div>
              {version.change_note && (
                <p className="text-xs text-muted-foreground/80 mb-2 italic">&ldquo;{version.change_note}&rdquo;</p>
              )}
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 text-xs px-2"
                  onClick={() => setViewingDiffId(viewingDiffId === version.id ? null : version.id)}
                >
                  <GitCompare className="mr-1 h-3 w-3" />
                  {viewingDiffId === version.id ? 'Hide Diff' : 'View Diff'}
                </Button>
                {index > 0 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 text-xs px-2"
                    onClick={() => setRestoreTarget(version)}
                  >
                    <RotateCcw className="mr-1 h-3 w-3" />
                    Restore
                  </Button>
                )}
              </div>
              {viewingDiffId === version.id && (
                <div className="mt-3">
                  <ConfigDiffViewer
                    serviceName={serviceName}
                    filename={filename}
                    versionId={version.id}
                    onClose={() => setViewingDiffId(null)}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>

      <AlertDialog open={!!restoreTarget} onOpenChange={(open) => !open && setRestoreTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Restore version {restoreTarget?.version_number}?</AlertDialogTitle>
            <AlertDialogDescription>
              This will create a new version with the restored content. The current version will still be available in history.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => restoreTarget && restoreMutation.mutate(restoreTarget)}
              disabled={restoreMutation.isPending}
            >
              {restoreMutation.isPending ? 'Restoring...' : 'Restore'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
