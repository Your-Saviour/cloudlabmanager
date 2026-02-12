import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FolderOpen, FileText, Upload, Trash2, Download, Pencil, Save, X } from 'lucide-react'
import api from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { toast } from 'sonner'

interface ServiceFile {
  name: string
  size: number
  modified: string
}

const subdirs = ['inputs', 'outputs']
const MAX_EDIT_SIZE = 102400 // 100KB - same as old app

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function ServiceFilesPage() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [activeDir, setActiveDir] = useState('inputs')
  const [deleteFile, setDeleteFile] = useState<string | null>(null)
  const [editingFile, setEditingFile] = useState<string | null>(null)
  const [editContent, setEditContent] = useState('')
  const [editDirty, setEditDirty] = useState(false)

  const { data: files = [], isLoading } = useQuery({
    queryKey: ['service', name, 'files', activeDir],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${name}/files/${activeDir}`)
      return (data.files || []) as ServiceFile[]
    },
    enabled: !!name,
  })

  const deleteMutation = useMutation({
    mutationFn: (filename: string) => api.delete(`/api/services/${name}/files/${activeDir}/${filename}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service', name, 'files', activeDir] })
      setDeleteFile(null)
      toast.success('File deleted')
    },
    onError: () => toast.error('Delete failed'),
  })

  const saveMutation = useMutation({
    mutationFn: ({ filename, content }: { filename: string; content: string }) =>
      api.put(`/api/services/${name}/files/${activeDir}/${filename}`, { content }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service', name, 'files', activeDir] })
      setEditDirty(false)
      toast.success('File saved')
    },
    onError: () => toast.error('Save failed'),
  })

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    try {
      await api.post(`/api/services/${name}/files/${activeDir}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      queryClient.invalidateQueries({ queryKey: ['service', name, 'files', activeDir] })
      toast.success('File uploaded')
    } catch {
      toast.error('Upload failed')
    }
    e.target.value = ''
  }

  const handleDownload = async (filename: string) => {
    try {
      const { data } = await api.get(`/api/services/${name}/files/${activeDir}/${filename}`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(data)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Download failed')
    }
  }

  const handleEdit = async (filename: string) => {
    try {
      const { data } = await api.get(`/api/services/${name}/files/${activeDir}/${filename}`, {
        responseType: 'text',
        transformResponse: [(data: string) => data],
      })
      setEditContent(data)
      setEditingFile(filename)
      setEditDirty(false)
    } catch {
      toast.error('Could not load file')
    }
  }

  const handleSaveEdit = () => {
    if (!editingFile) return
    saveMutation.mutate({ filename: editingFile, content: editContent })
  }

  const handleCloseEdit = () => {
    setEditingFile(null)
    setEditContent('')
    setEditDirty(false)
  }

  const switchDir = (dir: string) => {
    setActiveDir(dir)
    handleCloseEdit()
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="icon" onClick={() => navigate('/services')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">{name} - Files</h1>
          <p className="text-sm text-muted-foreground">Browse service input and output files</p>
        </div>
        <label className="cursor-pointer">
          <input type="file" className="hidden" onChange={handleUpload} />
          <Button size="sm" asChild>
            <span><Upload className="mr-2 h-3 w-3" /> Upload</span>
          </Button>
        </label>
      </div>

      <div className="flex gap-2 mb-4">
        {subdirs.map((dir) => (
          <Button
            key={dir}
            variant={activeDir === dir ? 'default' : 'outline'}
            size="sm"
            onClick={() => switchDir(dir)}
          >
            <FolderOpen className="mr-2 h-3 w-3" /> {dir}
          </Button>
        ))}
      </div>

      <Card>
        <CardContent className="pt-4">
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
            </div>
          ) : files.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No files in {activeDir}/</p>
          ) : (
            <div className="space-y-1">
              {files.map((file) => (
                <div key={file.name} className="flex items-center justify-between px-3 py-2 rounded-md hover:bg-muted/30">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="text-sm truncate">{file.name}</span>
                    <span className="text-xs text-muted-foreground shrink-0">{formatSize(file.size)}</span>
                  </div>
                  <div className="flex gap-1">
                    {file.size <= MAX_EDIT_SIZE && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => handleEdit(file.name)}
                        title="Edit"
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
                    )}
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => handleDownload(file.name)} title="Download">
                      <Download className="h-3 w-3" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setDeleteFile(file.name)} title="Delete">
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Inline File Editor */}
      {editingFile && (
        <Card className="mt-4">
          <CardContent className="pt-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">{editingFile}</span>
                {editDirty && <span className="text-xs text-muted-foreground">(modified)</span>}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleCloseEdit}
                >
                  <X className="mr-1 h-3 w-3" /> Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={handleSaveEdit}
                  disabled={!editDirty || saveMutation.isPending}
                >
                  <Save className="mr-1 h-3 w-3" /> {saveMutation.isPending ? 'Saving...' : 'Save'}
                </Button>
              </div>
            </div>
            <textarea
              className="w-full h-[400px] bg-black/30 rounded-md p-4 font-mono text-xs text-foreground resize-none border border-border focus:outline-none focus:ring-1 focus:ring-primary"
              value={editContent}
              onChange={(e) => { setEditContent(e.target.value); setEditDirty(true) }}
              spellCheck={false}
            />
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={!!deleteFile}
        onOpenChange={() => setDeleteFile(null)}
        title="Delete File"
        description={`Delete "${deleteFile}"? This cannot be undone.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteFile && deleteMutation.mutate(deleteFile)}
      />
    </div>
  )
}
