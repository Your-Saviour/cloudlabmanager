import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

interface ConfigDiffViewerProps {
  serviceName: string
  filename: string
  versionId: number
  onClose: () => void
}

export default function ConfigDiffViewer({ serviceName, filename, versionId, onClose }: ConfigDiffViewerProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['service', serviceName, 'config', filename, 'versions', versionId, 'diff'],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${serviceName}/configs/${filename}/versions/${versionId}/diff`)
      return data as {
        diff: string
        from_version: { id: number; version_number: number } | null
        to_version: { id: number; version_number: number }
      }
    },
  })

  const getLineClass = (line: string) => {
    if (line.startsWith('+')) return 'text-green-400 bg-green-400/10'
    if (line.startsWith('-')) return 'text-red-400 bg-red-400/10'
    if (line.startsWith('@@')) return 'text-blue-400'
    return 'text-muted-foreground'
  }

  return (
    <div className="border border-border rounded-md overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-muted/50 border-b border-border">
        <span className="text-sm font-medium">
          {data ? (
            <>
              Changes in v{data.to_version.version_number}
              {data.from_version ? ` (compared to v${data.from_version.version_number})` : ' (initial version)'}
            </>
          ) : (
            'Loading diff...'
          )}
        </span>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-3 w-3" />
        </Button>
      </div>
      <div className="p-4 overflow-x-auto">
        {isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : !data?.diff ? (
          <p className="text-sm text-muted-foreground text-center py-4">No differences found (initial version).</p>
        ) : (
          <pre className="text-xs font-mono leading-relaxed">
            {data.diff.split('\n').map((line, i) => (
              <div key={i} className={getLineClass(line)}>
                {line || '\u00A0'}
              </div>
            ))}
          </pre>
        )}
      </div>
    </div>
  )
}
