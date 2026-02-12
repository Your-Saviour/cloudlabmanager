import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Save, FileText } from 'lucide-react'
import api from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'

interface ConfigFile {
  name: string
  exists: boolean
}

export default function ServiceConfigPage() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [activeFile, setActiveFile] = useState<string>('')
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)

  const { data: configData, isLoading } = useQuery({
    queryKey: ['service', name, 'configs'],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${name}/configs`)
      return data as { configs: ConfigFile[]; service_dir: string }
    },
    enabled: !!name,
  })

  // Only show configs that actually exist on disk
  const configs = (configData?.configs || []).filter((c) => c.exists)

  // Auto-select first config when loaded
  useEffect(() => {
    if (configs.length > 0 && !activeFile) {
      setActiveFile(configs[0].name)
    }
  }, [configs.length])

  const { data: fileContent, isLoading: fileLoading } = useQuery({
    queryKey: ['service', name, 'config', activeFile],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${name}/configs/${activeFile}`)
      return data.content as string
    },
    enabled: !!name && !!activeFile,
  })

  // Sync file content into editor state
  useEffect(() => {
    if (fileContent !== undefined && !dirty) {
      setContent(fileContent)
    }
  }, [fileContent])

  const saveMutation = useMutation({
    mutationFn: () => api.put(`/api/services/${name}/configs/${activeFile}`, { content }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service', name, 'config', activeFile] })
      setDirty(false)
      toast.success('Config saved')
    },
    onError: () => toast.error('Save failed'),
  })

  const selectFile = (fileName: string) => {
    setActiveFile(fileName)
    setDirty(false)
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="icon" onClick={() => navigate('/services')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">{name} - Config</h1>
          <p className="text-sm text-muted-foreground">Edit service configuration files</p>
        </div>
        {dirty && (
          <Button size="sm" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
            <Save className="mr-2 h-3 w-3" /> Save
          </Button>
        )}
      </div>

      {isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : configs.length === 0 ? (
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground text-center py-6">No config files found for this service.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-[200px_1fr] gap-4">
          <Card>
            <CardContent className="pt-4">
              <nav className="space-y-1">
                {configs.map((file) => (
                  <button
                    key={file.name}
                    className={`flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm transition-colors ${
                      activeFile === file.name ? 'bg-primary/10 text-primary' : 'hover:bg-muted/50 text-muted-foreground'
                    }`}
                    onClick={() => selectFile(file.name)}
                  >
                    <FileText className="h-3 w-3" />
                    {file.name}
                  </button>
                ))}
              </nav>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              {fileLoading ? (
                <Skeleton className="h-96 w-full" />
              ) : (
                <textarea
                  className="w-full h-[500px] bg-black/30 rounded-md p-4 font-mono text-xs text-foreground resize-none border border-border focus:outline-none focus:ring-1 focus:ring-primary"
                  value={content}
                  onChange={(e) => { setContent(e.target.value); setDirty(true) }}
                  spellCheck={false}
                />
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
